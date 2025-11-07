"""
Lineage analysis tools for Architect Agent.

Provides @agent_tool decorated functions for recursive lineage analysis.
"""

import json
from typing import Dict, List, Any, Optional
from datetime import datetime
from google.cloud import bigquery

# For production: from google.adk.tools import agent_tool
def agent_tool(func):
    """Decorator marking function as agent tool."""
    return func

_bq_client: Optional[bigquery.Client] = None

def get_bq_client() -> bigquery.Client:
    """Get or create BigQuery client."""
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client()
    return _bq_client

@agent_tool
def analyze_lineage_upstream(
    project_id: str,
    object_id: str,
    dataset_id: str = "minietl",
    max_depth: int = 10
) -> Dict[str, Any]:
    """Recursively analyze upstream dependencies (what feeds into this object)."""
    try:
        client = get_bq_client()
        query = f"""
        WITH RECURSIVE upstream AS (
            SELECT e.source_object_id, o.name, o.object_type,
                   'UNREVIEWED' as priority,
                   e.edge_type, 1 as depth,
                   ARRAY<STRING>['{object_id}'] as path
            FROM `{project_id}.{dataset_id}.etledges` e
            JOIN `{project_id}.{dataset_id}.etlobjectscd2` o
              ON e.source_object_id = o.object_id AND o.effective_end IS NULL
            WHERE e.target_object_id = '{object_id}' AND e.is_active = TRUE
            UNION ALL
            SELECT e.source_object_id, o.name, o.object_type,
                   'UNREVIEWED' as priority,
                   e.edge_type, u.depth + 1,
                   ARRAY_CONCAT(u.path, [e.target_object_id])
            FROM upstream u
            JOIN `{project_id}.{dataset_id}.etledges` e
              ON u.object_id = e.target_object_id AND e.is_active = TRUE
            JOIN `{project_id}.{dataset_id}.etlobjectscd2` o
              ON e.source_object_id = o.object_id AND o.effective_end IS NULL
            WHERE u.depth < {max_depth}
              AND NOT e.source_object_id IN UNNEST(u.path)
        )
        SELECT DISTINCT object_id, name, object_type, priority, edge_type,
               depth, ARRAY_LENGTH(path) + 1 as hops_from_target
        FROM upstream ORDER BY depth, name
        """
        results = list(client.query(query).result())
        upstream_deps = [{"object_id": r.object_id, "name": r.name,
                         "object_type": r.object_type, "priority": r.priority,
                         "edge_type": r.edge_type, "depth_level": r.depth,
                         "hops_from_target": r.hops_from_target} for r in results]
        depth_summary = {}
        for dep in upstream_deps:
            depth = dep["depth_level"]
            depth_summary[depth] = depth_summary.get(depth, 0) + 1
        return {"status": "success", "object_id": object_id,
                "direction": "UPSTREAM", "total_upstream": len(upstream_deps),
                "depth_levels": len(depth_summary), "by_depth": depth_summary,
                "dependencies": upstream_deps}
    except Exception as e:
        return {"status": "error", "error": str(e)}

@agent_tool
def analyze_lineage_downstream(
    project_id: str,
    object_id: str,
    dataset_id: str = "minietl",
    max_depth: int = 10
) -> Dict[str, Any]:
    """Recursively analyze downstream dependencies (what depends on this object)."""
    try:
        client = get_bq_client()
        query = f"""
        WITH RECURSIVE downstream AS (
            SELECT e.target_object_id, o.name, o.object_type,
                   'UNREVIEWED' as priority,
                   e.edge_type, 1 as depth,
                   ARRAY<STRING>['{object_id}'] as path
            FROM `{project_id}.{dataset_id}.etledges` e
            JOIN `{project_id}.{dataset_id}.etlobjectscd2` o
              ON e.target_object_id = o.object_id AND o.effective_end IS NULL
            WHERE e.source_object_id = '{object_id}' AND e.is_active = TRUE
            UNION ALL
            SELECT e.target_object_id, o.name, o.object_type,
                   'UNREVIEWED' as priority,
                   e.edge_type, d.depth + 1,
                   ARRAY_CONCAT(d.path, [e.source_object_id])
            FROM downstream d
            JOIN `{project_id}.{dataset_id}.etledges` e
              ON d.object_id = e.source_object_id AND e.is_active = TRUE
            JOIN `{project_id}.{dataset_id}.etlobjectscd2` o
              ON e.target_object_id = o.object_id AND o.effective_end IS NULL
            WHERE d.depth < {max_depth}
              AND NOT e.target_object_id IN UNNEST(d.path)
        )
        SELECT DISTINCT object_id, name, object_type, priority, edge_type,
               depth, ARRAY_LENGTH(path) + 1 as hops_from_source
        FROM downstream ORDER BY depth, name
        """
        results = list(client.query(query).result())
        downstream_deps = [{"object_id": r.object_id, "name": r.name,
                           "object_type": r.object_type, "priority": r.priority,
                           "edge_type": r.edge_type, "depth_level": r.depth,
                           "hops_from_source": r.hops_from_source} for r in results]
        depth_summary = {}
        for dep in downstream_deps:
            depth = dep["depth_level"]
            depth_summary[depth] = depth_summary.get(depth, 0) + 1
        return {"status": "success", "object_id": object_id,
                "direction": "DOWNSTREAM", "total_downstream": len(downstream_deps),
                "depth_levels": len(depth_summary), "by_depth": depth_summary,
                "dependencies": downstream_deps}
    except Exception as e:
        return {"status": "error", "error": str(e)}

@agent_tool
def build_lineage_graph(
    project_id: str,
    object_id: str,
    dataset_id: str = "minietl",
    include_scope: str = "both"
) -> Dict[str, Any]:
    """Build complete lineage graph for an object."""
    try:
        client = get_bq_client()
        nodes_map = {}
        target_query = f"""
        SELECT object_id, name, object_type, priority
        FROM `{project_id}.{dataset_id}.etlobjectscd2`
        WHERE object_id = '{object_id}' AND effective_end IS NULL LIMIT 1
        """
        target_result = list(client.query(target_query).result())
        if not target_result:
            return {"status": "error", "error": f"Object {object_id} not found"}
        target = target_result[0]
        nodes_map[object_id] = {"object_id": object_id, "name": target.name,
                               "object_type": target.object_type,
                               "priority": target.priority or "UNREVIEWED",
                               "is_target": True}
        edges_list = []
        
        if include_scope in ["upstream", "both"]:
            upstream_query = f"""
            WITH RECURSIVE upstream AS (
                SELECT e.source_object_id, e.target_object_id, e.edge_type, 1 as depth,
                       ARRAY<STRING>['{object_id}'] as path
                FROM `{project_id}.{dataset_id}.etledges` e
                WHERE e.target_object_id = '{object_id}' AND e.is_active = TRUE
                UNION ALL
                SELECT e.source_object_id, e.target_object_id, e.edge_type, u.depth + 1,
                       ARRAY_CONCAT(u.path, [e.target_object_id])
                FROM upstream u
                JOIN `{project_id}.{dataset_id}.etledges` e
                  ON u.source_object_id = e.target_object_id AND e.is_active = TRUE
                WHERE u.depth < 5 AND NOT e.source_object_id IN UNNEST(u.path)
            )
            SELECT source_object_id, target_object_id, edge_type FROM upstream
            """
            for row in client.query(upstream_query).result():
                edges_list.append({"source": row.source_object_id,
                                 "target": row.target_object_id,
                                 "edge_type": row.edge_type})
                if row.source_object_id not in nodes_map:
                    nodes_map[row.source_object_id] = None

        if include_scope in ["downstream", "both"]:
            downstream_query = f"""
            WITH RECURSIVE downstream AS (
                SELECT e.source_object_id, e.target_object_id, e.edge_type, 1 as depth,
                       ARRAY<STRING>['{object_id}'] as path
                FROM `{project_id}.{dataset_id}.etledges` e
                WHERE e.source_object_id = '{object_id}' AND e.is_active = TRUE
                UNION ALL
                SELECT e.source_object_id, e.target_object_id, e.edge_type, d.depth + 1,
                       ARRAY_CONCAT(d.path, [e.source_object_id])
                FROM downstream d
                JOIN `{project_id}.{dataset_id}.etledges` e
                  ON d.target_object_id = e.source_object_id AND e.is_active = TRUE
                WHERE d.depth < 5 AND NOT e.target_object_id IN UNNEST(d.path)
            )
            SELECT source_object_id, target_object_id, edge_type FROM downstream
            """
            for row in client.query(downstream_query).result():
                edges_list.append({"source": row.source_object_id,
                                 "target": row.target_object_id,
                                 "edge_type": row.edge_type})
                if row.target_object_id not in nodes_map:
                    nodes_map[row.target_object_id] = None

        missing_ids = [oid for oid, node in nodes_map.items() if node is None]
        if missing_ids:
            ids_str = "', '".join(missing_ids)
            fetch_query = f"""
            SELECT object_id, name, object_type, priority
            FROM `{project_id}.{dataset_id}.etlobjectscd2`
            WHERE object_id IN ('{ids_str}') AND effective_end IS NULL
            """
            for row in client.query(fetch_query).result():
                nodes_map[row.object_id] = {"object_id": row.object_id,
                                           "name": row.name,
                                           "object_type": row.object_type,
                                           "priority": row.priority or "UNREVIEWED",
                                           "is_target": False}

        nodes = [node for node in nodes_map.values() if node is not None]
        edges = [{"source": e['source'], "target": e['target'], 
                 "type": e['edge_type']} for e in edges_list]
        downstream_counts = {}
        for edge in edges_list:
            downstream_counts[edge['source']] = downstream_counts.get(edge['source'], 0) + 1
        critical_nodes = [oid for oid, count in downstream_counts.items() if count > 3]
        
        return {"status": "success", "object_id": object_id,
                "node_count": len(nodes), "edge_count": len(edges),
                "critical_nodes": critical_nodes, "nodes": nodes, "edges": edges}
    except Exception as e:
        return {"status": "error", "error": str(e)}

@agent_tool
def extract_critical_paths(
    project_id: str,
    dataset_id: str = "minietl"
) -> Dict[str, Any]:
    """Identify critical dependency paths in entire system."""
    try:
        client = get_bq_client()
        roots_query = f"""
        SELECT DISTINCT o.object_id, o.name, o.object_type,
               'UNREVIEWED' as priority
        FROM `{project_id}.{dataset_id}.etlobjectscd2` o
        LEFT JOIN `{project_id}.{dataset_id}.etledges` e
          ON o.object_id = e.target_object_id AND e.is_active = TRUE
        WHERE o.effective_end IS NULL AND o.status = 'active'
          AND e.target_object_id IS NULL
        """
        roots = list(client.query(roots_query).result())
        critical_paths = []
        for root in roots:
            reach_query = f"""
            WITH RECURSIVE reachable AS (
                SELECT '{root.object_id}' as object_id, 0 as depth, 1 as path_count
                UNION ALL
                SELECT e.target_object_id, r.depth + 1, r.path_count + 1
                FROM reachable r
                JOIN `{project_id}.{dataset_id}.etledges` e
                  ON r.object_id = e.source_object_id AND e.is_active = TRUE
                WHERE r.depth < 10
            )
            SELECT COUNT(*) as reachable_count, MAX(depth) as max_depth FROM reachable
            """
            reach_result = list(client.query(reach_query).result())[0]
            if reach_result.reachable_count > 3:
                critical_paths.append({
                    "root_id": root.object_id, "root_name": root.name,
                    "root_type": root.object_type, "root_priority": root.priority,
                    "reachable_objects": reach_result.reachable_count,
                    "max_depth": reach_result.max_depth or 0,
                    "criticality_score": reach_result.reachable_count * (reach_result.max_depth or 1)
                })
        critical_paths.sort(key=lambda x: x["criticality_score"], reverse=True)
        return {"status": "success", "total_critical_paths": len(critical_paths),
                "paths": critical_paths[:20]}
    except Exception as e:
        return {"status": "error", "error": str(e)}
