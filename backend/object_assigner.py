"""
Object ID assignment system for ETL objects.

Handles:
- Auto-generating object IDs (OBJ001, OBJ002, ...)
- Assigning IDs to collected objects
- Bulk assignment from inventory
- Tracking assigned IDs
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Union

from backend.models import ETLObject, ETLEdge, ObjectType

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ObjectIDAssigner:
    """Assigns unique object IDs to ETL objects."""

    def __init__(self, start_id: int = 1):
        """
        Initialize assigner.

        Args:
            start_id: Starting ID number (default: 1)
        """
        self.next_id = start_id
        self.assignments: Dict[str, str] = {}  # composite key -> object_id
        self.reverse_assignments: Dict[str, Dict[str, Optional[str]]] = {}  # object_id -> {"name": str, "object_type": str}

    @staticmethod
    def _make_key(name: str, object_type: Optional[Union[ObjectType, str]]) -> str:
        """
        Build the de-duplicated assignment key.

        Names across different object types collide frequently (e.g. trigger +
        function with the same friendly name), so we namespace the key.
        """
        if isinstance(object_type, ObjectType):
            type_value = object_type.value
        elif object_type:
            type_value = str(object_type)
        else:
            return name
        return f"{type_value}::{name}"

    def _record_assignment(self, key: str, obj_id: str, obj: ETLObject) -> None:
        """Persist assignment metadata in both forward and reverse caches."""
        self.assignments[key] = obj_id
        self.reverse_assignments[obj_id] = {
            "name": obj.name,
            "object_type": obj.object_type.value if isinstance(obj.object_type, ObjectType) else str(obj.object_type),
        }

    def get_next_id(self) -> str:
        """Generate next object ID."""
        obj_id = f"OBJ{self.next_id:04d}"
        self.next_id += 1
        return obj_id

    def assign_object(self, obj: ETLObject) -> Tuple[str, ETLObject]:
        """
        Assign ID to an ETL object.

        Args:
            obj: ETLObject instance

        Returns:
            Tuple of (assigned_id, updated_object)
        """
        key = self._make_key(obj.name, obj.object_type)
        # Support legacy name-only assignments for backwards compatibility.
        legacy_key = obj.name
        cached_id = self.assignments.get(key) or self.assignments.get(legacy_key)

        if cached_id:
            obj.object_id = cached_id
            # Ensure forward/reverse maps use the canonical key format.
            self._record_assignment(key, cached_id, obj)
            if legacy_key != key:
                self.assignments.pop(legacy_key, None)
            return cached_id, obj

        # Generate new ID
        obj_id = self.get_next_id()
        obj.object_id = obj_id

        # Record assignment
        self._record_assignment(key, obj_id, obj)
        if legacy_key != key:
            self.assignments.pop(legacy_key, None)

        logger.debug(f"Assigned {obj_id} to {obj.object_type.value}: {obj.name}")
        return obj_id, obj

    def assign_all(self, objects: List[ETLObject]) -> List[ETLObject]:
        """
        Assign IDs to all objects.

        Args:
            objects: List of ETLObject instances

        Returns:
            List of objects with assigned IDs
        """
        logger.info(f"Assigning IDs to {len(objects)} objects...")

        assigned_objects = []
        for obj in objects:
            _, assigned_obj = self.assign_object(obj)
            assigned_objects.append(assigned_obj)

        logger.info(f"✓ Assigned {len(assigned_objects)} object IDs")
        return assigned_objects

    def assign_edges(self, objects: List[ETLObject], edges: List[ETLEdge]) -> List[ETLEdge]:
        """
        Assign object IDs to edges based on object names.

        Args:
            objects: List of ETLObject instances (with assigned IDs)
            edges: List of ETLEdge instances

        Returns:
            List of edges with assigned object IDs
        """
        logger.info(f"Assigning object IDs to {len(edges)} edges...")

        # Build reverse map of names to IDs
        name_to_id = {obj.name: obj.object_id for obj in objects}

        assigned_edges = []
        unresolved = 0

        for edge in edges:
            source_id = name_to_id.get(edge.source_name)
            target_id = name_to_id.get(edge.target_name)

            if not source_id:
                logger.debug(f"Could not resolve source: {edge.source_name}")
                unresolved += 1

            if not target_id:
                logger.debug(f"Could not resolve target: {edge.target_name}")
                unresolved += 1

            if source_id and target_id:
                edge.source_object_id = source_id
                edge.target_object_id = target_id
                assigned_edges.append(edge)

        logger.info(
            f"✓ Assigned {len(assigned_edges)} edges "
            f"({unresolved} unresolved object references)"
        )

        return assigned_edges

    def set_parent_relationships(self, objects: List[ETLObject]) -> List[ETLObject]:
        """
        Set parent_id relationships for child objects.

        Args:
            objects: List of ETLObject instances

        Returns:
            Updated list with parent relationships
        """
        logger.info("Setting parent relationships...")

        name_to_obj = {obj.name: obj for obj in objects}

        for obj in objects:
            # BigQuery tables inherit from datasets
            if obj.object_type.value == "BQTABLE" and "." in obj.name:
                dataset_name = obj.name.split(".")[0]
                if dataset_name in name_to_obj:
                    obj.parent_id = name_to_obj[dataset_name].object_id
                    logger.debug(f"Set parent of {obj.name} to {dataset_name}")

        return objects

    def save_assignments(self, output_file: str) -> None:
        """
        Save assignments to JSON file.

        Args:
            output_file: Path to output file
        """
        data = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "total_assignments": len(self.assignments),
            "assignments": self.assignments,
        }

        try:
            with open(output_file, "w") as f:
                json.dump(data, f, indent=2)
            logger.info(f"✓ Saved assignments to {output_file}")
        except Exception as e:
            logger.error(f"Failed to save assignments: {e}")
            raise

    def load_assignments(self, input_file: str) -> None:
        """
        Load assignments from JSON file.

        Args:
            input_file: Path to input file
        """
        try:
            with open(input_file, "r") as f:
                data = json.load(f)

            assignments = data.get("assignments", {})
            self.assignments = {}
            self.reverse_assignments = {}

            for stored_key, obj_id in assignments.items():
                if not obj_id:
                    continue

                if "::" in stored_key:
                    object_type, name = stored_key.split("::", 1)
                    key = self._make_key(name, object_type)
                    self.assignments[key] = obj_id
                    self.reverse_assignments[obj_id] = {
                        "name": name,
                        "object_type": object_type,
                    }
                else:
                    # Legacy format: name-only keys.
                    self.assignments[stored_key] = obj_id
                    self.reverse_assignments[obj_id] = {
                        "name": stored_key,
                        "object_type": None,
                    }

            # Update next_id based on highest existing ID
            if self.reverse_assignments:
                max_id = max(
                    int(obj_id.replace("OBJ", ""))
                    for obj_id in self.reverse_assignments.keys()
                )
                self.next_id = max_id + 1

            logger.info(f"✓ Loaded {len(assignments)} assignments from {input_file}")
        except Exception as e:
            logger.error(f"Failed to load assignments: {e}")
            raise

    def get_assignment(
        self,
        name: str,
        object_type: Optional[Union[ObjectType, str]] = None,
    ) -> Optional[str]:
        """Get assigned ID for an object name."""
        keys: List[str] = []
        if object_type is not None:
            keys.append(self._make_key(name, object_type))
        keys.append(name)  # legacy fallback

        for key in keys:
            if key in self.assignments:
                return self.assignments[key]
        return None

    def get_name(self, object_id: str) -> Optional[str]:
        """Get object name from ID."""
        entry = self.reverse_assignments.get(object_id)
        if isinstance(entry, dict):
            return entry.get("name")
        return entry

    def export_assignments_csv(self, output_file: str) -> None:
        """
        Export assignments to CSV format.

        Args:
            output_file: Path to output CSV file
        """
        try:
            with open(output_file, "w") as f:
                f.write("object_id,object_type,name\n")
                for obj_id in sorted(self.reverse_assignments.keys()):
                    entry = self.reverse_assignments[obj_id]
                    if isinstance(entry, dict):
                        name = entry.get("name", "")
                        object_type = entry.get("object_type", "") or ""
                    else:
                        name = entry or ""
                        object_type = ""
                    f.write(f"{obj_id},{object_type},{name}\n")

            logger.info(f"✓ Exported assignments to {output_file}")
        except Exception as e:
            logger.error(f"Failed to export CSV: {e}")
            raise


class InteractiveAssigner:
    """Interactive assignment interface for user-driven ID assignment."""

    def __init__(self, assigner: ObjectIDAssigner):
        """
        Initialize interactive assigner.

        Args:
            assigner: ObjectIDAssigner instance
        """
        self.assigner = assigner

    def assign_interactive(self, objects: List[ETLObject]) -> List[ETLObject]:
        """
        Interactively assign IDs to objects with user input.

        Args:
            objects: List of ETLObject instances

        Returns:
            List of objects with assigned IDs
        """
        logger.info(f"Interactive assignment mode for {len(objects)} objects")
        logger.info("Enter object ID or press Enter to auto-assign (or 'q' to quit)\n")

        assigned = []

        for i, obj in enumerate(objects, 1):
            print(f"\n[{i}/{len(objects)}] {obj.object_type.value}: {obj.name}")
            if obj.description:
                print(f"  Description: {obj.description}")

            while True:
                user_input = input("Assign ID (or Enter for auto): ").strip().upper()

                if user_input == "Q":
                    logger.info("Assignment cancelled")
                    return assigned

                if user_input == "":
                    # Auto-assign
                    obj_id, obj = self.assigner.assign_object(obj)
                    print(f"  ✓ Auto-assigned: {obj_id}")
                    break

                elif user_input.startswith("OBJ"):
                    # User-provided ID
                    obj.object_id = user_input
                    key = self.assigner._make_key(obj.name, obj.object_type)
                    self.assigner.assignments[key] = user_input
                    self.assigner.reverse_assignments[user_input] = {
                        "name": obj.name,
                        "object_type": obj.object_type.value
                        if isinstance(obj.object_type, ObjectType)
                        else str(obj.object_type),
                    }
                    print(f"  ✓ Assigned: {user_input}")
                    break

                else:
                    print("  Invalid ID format. Use OBJNNN or press Enter for auto-assign")

            assigned.append(obj)

        logger.info(f"✓ Assigned {len(assigned)} objects interactively")
        return assigned
