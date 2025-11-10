"""
Enhanced Architect Agent with Gemini for Smart Object Parsing.

Replaces custom regex parser (architect_object_parser.py) with LLM intelligence
for unlimited format support and context-aware analysis.

Features:
- Gemini function calling for intent detection
- Session-based conversation context
- Three specialized tools: get_object, analyze_lineage, generate_diagram
- Automatic object ID normalization
- Intelligent lineage chain parsing
"""

import json
import logging
from typing import Dict, List, Any, Optional
import asyncio

try:
    from google import genai
except ImportError:
    genai = None

logger = logging.getLogger(__name__)


class ArchitectAgentGeminiEnhanced:
    """
    Architect Agent using Gemini for intelligent object understanding.

    Processes natural language queries and object references, leveraging Gemini
    for intent detection and context-aware analysis.
    """

    SYSTEM_INSTRUCTION = """You are an architect agent analyzing GCP infrastructure.

When a user provides object IDs in any format:
- Normalize them (e.g., "0002" becomes "OBJ0002")
- Detect intent (lineage vs. single object vs. diagram generation)
- Call the appropriate tool with normalized IDs
- Provide context-aware analysis

Examples:
- "0002->0004->0027" → Call analyze_lineage with ordered chain
- "0002, 0004" → Call get_object for each
- "Show diagram for 0002" → Call generate_diagram
- "0002 and its dependencies" → Call analyze_lineage

Always normalize object IDs to OBJ#### format (4 digits, zero-padded).
"""

    def __init__(self, bq_manager, gemini_api_key: Optional[str] = None):
        """
        Initialize Gemini-enhanced architect agent.

        Args:
            bq_manager: BigQueryManager instance for data access
            gemini_api_key: Optional Gemini API key (uses GOOGLE_API_KEY env var if not provided)
        """
        self.bq_manager = bq_manager
        self.session_state = {}

        if genai is None:
            logger.warning("google-genai not installed. Gemini features will not work.")
            self.gemini_client = None
            return

        # Initialize Gemini client
        try:
            if gemini_api_key:
                genai.configure(api_key=gemini_api_key)
            self.gemini_client = genai.Client()
            logger.info("✓ Gemini client initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Gemini client: {e}")
            self.gemini_client = None

    def define_tools(self) -> List[Dict[str, Any]]:
        """Define tools that Gemini can call."""
        return [
            {
                "name": "get_object",
                "description": "Get details for a single object ID",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "object_id": {
                            "type": "string",
                            "description": "Object ID like '0002' or 'OBJ0002'"
                        }
                    },
                    "required": ["object_id"]
                }
            },
            {
                "name": "analyze_lineage",
                "description": "Analyze lineage chain and dependencies for objects",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "object_chain": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Objects in lineage order (e.g., ['OBJ0002', 'OBJ0004', 'OBJ0027'])"
                        }
                    },
                    "required": ["object_chain"]
                }
            },
            {
                "name": "generate_diagram",
                "description": "Generate architecture diagram for given objects",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "objects": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of object IDs to include in diagram"
                        }
                    },
                    "required": ["objects"]
                }
            }
        ]

    def _normalize_object_id(self, obj_id: str) -> str:
        """
        Normalize object ID to standard format OBJ####.

        Args:
            obj_id: Object ID in various formats (0002, OBJ0002, 2, etc.)

        Returns:
            Normalized format: OBJ0002
        """
        if not obj_id:
            return None

        obj_id = str(obj_id).strip().upper()

        # Already in OBJ format
        if obj_id.startswith('OBJ'):
            import re
            match = re.match(r'OBJ(\d+)', obj_id)
            if match:
                num = int(match.group(1))
                return f"OBJ{num:04d}"
            return obj_id

        # Shorthand format (just numbers)
        import re
        match = re.match(r'^(\d+)$', obj_id)
        if match:
            num = int(match.group(1))
            return f"OBJ{num:04d}"

        return None

    async def process_user_input(self, user_message: str) -> Dict[str, Any]:
        """
        Process user message using Gemini for parsing and intent detection.

        Args:
            user_message: Natural language query or object reference

        Returns:
            Dictionary with parsed objects, operations, and analysis

        Example:
            User: "0002->0004->0027"
            Gemini: Detects lineage pattern, calls analyze_lineage()
            Returns: {
                "message": "Found lineage chain...",
                "objects": ["OBJ0002", "OBJ0004", "OBJ0027"],
                "operations": ["analyze_lineage"],
                ...
            }
        """
        if not self.gemini_client:
            logger.error("Gemini client not initialized")
            return {
                "error": "Gemini not configured",
                "message": "google-genai not installed or API key not set"
            }

        logger.info(f"Processing user input: {user_message}")

        # Store in session for context
        self.session_state["messages"] = self.session_state.get("messages", [])
        self.session_state["messages"].append({
            "role": "user",
            "content": user_message
        })

        try:
            # Call Gemini with function calling
            response = await asyncio.to_thread(
                self.gemini_client.models.generate_content,
                model="gemini-2.0-flash",
                contents=user_message,
                tools=self.define_tools(),
                system_instruction=self.SYSTEM_INSTRUCTION
            )

            # Process Gemini's response and tool calls
            result = self._handle_gemini_response(response)

            # Store response in session
            self.session_state["messages"].append({
                "role": "assistant",
                "content": result.get("message", "")
            })

            return result

        except Exception as e:
            logger.error(f"Gemini processing failed: {e}")
            return {
                "error": str(e),
                "message": f"Failed to process with Gemini: {str(e)}"
            }

    def _handle_gemini_response(self, response) -> Dict[str, Any]:
        """
        Handle Gemini's response and extract function calls.

        Args:
            response: Gemini API response object

        Returns:
            Dictionary with extracted objects, operations, and metadata
        """
        result = {
            "message": getattr(response, 'text', ''),
            "objects": [],
            "operations": [],
            "raw_response": None
        }

        try:
            # Extract function calls from response
            if hasattr(response, 'content') and response.content:
                for part in response.content.parts:
                    if hasattr(part, 'function_call') and part.function_call:
                        func_name = part.function_call.name
                        func_args = part.function_call.args if hasattr(part.function_call, 'args') else {}

                        logger.info(f"Gemini called function: {func_name} with args: {func_args}")

                        if func_name == "get_object":
                            obj_id = func_args.get("object_id")
                            normalized = self._normalize_object_id(obj_id)
                            if normalized:
                                result["objects"].append(normalized)

                        elif func_name == "analyze_lineage":
                            chain = func_args.get("object_chain", [])
                            # Normalize all object IDs in chain
                            normalized_chain = [self._normalize_object_id(oid) for oid in chain]
                            normalized_chain = [oid for oid in normalized_chain if oid]
                            result["objects"].extend(normalized_chain)
                            result["operations"].append("analyze_lineage")

                        elif func_name == "generate_diagram":
                            objects = func_args.get("objects", [])
                            normalized_objects = [self._normalize_object_id(oid) for oid in objects]
                            normalized_objects = [oid for oid in normalized_objects if oid]
                            result["objects"].extend(normalized_objects)
                            result["operations"].append("generate_diagram")

            # Remove duplicates while preserving order
            result["objects"] = list(dict.fromkeys(result["objects"]))

        except Exception as e:
            logger.error(f"Error handling Gemini response: {e}")
            result["error"] = str(e)

        return result

    def reset_session(self):
        """Reset session state for new conversation."""
        self.session_state = {}
        logger.info("Session state reset")

    def get_session_state(self) -> Dict[str, Any]:
        """Get current session state."""
        return self.session_state.copy()

    async def analyze_object_with_context(
        self,
        object_id: str,
        additional_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Analyze an object with optional additional context.

        Args:
            object_id: Object ID to analyze
            additional_context: Optional additional context for analysis

        Returns:
            Analysis result from Gemini
        """
        normalized_id = self._normalize_object_id(object_id)
        if not normalized_id:
            return {"error": f"Invalid object ID: {object_id}"}

        prompt = f"Analyze object {normalized_id}"
        if additional_context:
            prompt += f"\nContext: {additional_context}"

        return await self.process_user_input(prompt)
