#!/usr/bin/env python3
"""
V2 Translation Pipeline DAG Definition

Defines the translation pipeline as a proper DAG with parallel branches
and quality gates. The key insight: metadata, TOC, and headings are
independent and can run in parallel.

                    +------------+
                    |  SOURCE    |
                    |  LOADER    |
                    +-----+------+
                          |
               +----------+----------+
               |          |          |
         +-----v---+ +---v----+ +--v------+
         |METADATA | |  TOC   | |HEADINGS |
         +---------+ +--------+ +---------+
               |          |          |
               +----------+----------+
                          |
                    +-----v-----+
                    |   BODY    |
                    +-----+-----+
                          |
                   +------v------+
                   | QG: Footnote|
                   |  Integrity  |
                   +------+------+
                          |
                    +-----v-----+
                    |  SPECIAL  |
                    +-----+-----+
                          |
               +----------+----------+
               |          |          |
         +-----v---+ +---v----+ +--v------+ +---v------+
         |CLEANUP  | |CLEANUP | |CLEANUP  | |CLEANUP   |
         |  6a     |>|  6b    |>|  6c     |>|6d DRAMAT.|
         +---------+ +--------+ +---------+ +----------+
                                                  |
                   +------v------+
                   | QG: Post-   |
                   |  Cleanup    |
                   +------+------+
                          |
                    +-----v-----+
                    | VALIDATION|
                    +-----+-----+
                          |
                    +-----v-----+
                    | EPUB BUILD|
                    +-----+-----+
                          |
                    +-----v-----+
                    |SEND KINDLE|
                    +-----------+
"""

from workflows.dag_engine import (
    DAGDefinition,
    DAGNode,
    NodeType,
    NodeStatus,
    EdgeType,
)


def create_v2_pipeline_dag() -> DAGDefinition:
    """Create the V2 translation pipeline DAG definition."""
    dag = DAGDefinition()

    # --- Nodes ---
    dag.add_node(DAGNode(
        id="source_loader",
        display_name="Source Loader",
        node_type=NodeType.TASK,
        metadata={"icon": "folder", "color": "#607D8B", "description": "Load cleaned JSON source files"},
    ))

    dag.add_node(DAGNode(
        id="metadata",
        display_name="Metadata Translation",
        node_type=NodeType.TASK,
        metadata={"icon": "tag", "color": "#9C27B0", "description": "Translate title, author, publisher", "is_parallel": True},
    ))

    dag.add_node(DAGNode(
        id="toc",
        display_name="TOC Translation",
        node_type=NodeType.TASK,
        metadata={"icon": "list", "color": "#00BCD4", "description": "Translate table of contents", "is_parallel": True},
    ))

    dag.add_node(DAGNode(
        id="headings",
        display_name="Headings Translation",
        node_type=NodeType.TASK,
        metadata={"icon": "heading", "color": "#FF9800", "description": "Translate chapter headings", "is_parallel": True},
    ))

    dag.add_node(DAGNode(
        id="body",
        display_name="Body Translation",
        node_type=NodeType.TASK,
        metadata={"icon": "book", "color": "#2196F3", "description": "Translate main content with footnotes"},
    ))

    dag.add_node(DAGNode(
        id="qg_footnote_integrity",
        display_name="Footnote Integrity",
        node_type=NodeType.QUALITY_GATE,
        metadata={"icon": "shield", "color": "#F44336", "description": "Validate footnote markers match definitions", "halt_on_fail": True},
    ))

    dag.add_node(DAGNode(
        id="special",
        display_name="Special Sections",
        node_type=NodeType.TASK,
        metadata={"icon": "star", "color": "#795548", "description": "Translate front/back matter"},
    ))

    dag.add_node(DAGNode(
        id="cleanup_6a",
        display_name="Character Cleanup",
        node_type=NodeType.TASK,
        metadata={"icon": "user-x", "color": "#E91E63", "description": "Remove fictional character footnotes"},
    ))

    dag.add_node(DAGNode(
        id="cleanup_6b",
        display_name="Trivial Cleanup",
        node_type=NodeType.TASK,
        metadata={"icon": "filter", "color": "#673AB7", "description": "Remove over-explanatory footnotes"},
    ))

    dag.add_node(DAGNode(
        id="cleanup_6c",
        display_name="Density Validation",
        node_type=NodeType.TASK,
        metadata={"icon": "chart-bar", "color": "#3F51B5", "description": "Validate footnote density per block"},
    ))

    dag.add_node(DAGNode(
        id="cleanup_6d_dramatis",
        display_name="Dramatis Personae",
        node_type=NodeType.TASK,
        metadata={"icon": "users", "color": "#FF5722", "description": "Harvest character footnotes into Dramatis Personae"},
    ))

    dag.add_node(DAGNode(
        id="qg_post_cleanup",
        display_name="Post-Cleanup Gate",
        node_type=NodeType.QUALITY_GATE,
        metadata={"icon": "shield-check", "color": "#F44336", "description": "Validate footnotes after cleanup", "halt_on_fail": True},
    ))

    dag.add_node(DAGNode(
        id="validation",
        display_name="Final Validation",
        node_type=NodeType.TASK,
        metadata={"icon": "check-circle", "color": "#4CAF50", "description": "Verify translation completeness and quality", "is_terminal": False},
    ))

    dag.add_node(DAGNode(
        id="epub_build",
        display_name="EPUB Build",
        node_type=NodeType.TASK,
        metadata={"icon": "book-open", "color": "#009688", "description": "Generate final EPUB file"},
    ))

    dag.add_node(DAGNode(
        id="send_kindle",
        display_name="Send to Kindle",
        node_type=NodeType.TASK,
        metadata={
            "icon": "mail", "color": "#FF9800",
            "description": "Email EPUB to Kindle device(s)",
            "is_terminal": True, "optional": True,
        },
    ))

    # --- Edges ---
    # Source loader fans out to parallel translation stages
    dag.add_edge("source_loader", "metadata", EdgeType.DEPENDENCY)
    dag.add_edge("source_loader", "toc", EdgeType.DEPENDENCY)
    dag.add_edge("source_loader", "headings", EdgeType.DEPENDENCY)

    # Parallel stages converge into body translation
    dag.add_edge("metadata", "body", EdgeType.DEPENDENCY)
    dag.add_edge("toc", "body", EdgeType.DEPENDENCY)
    dag.add_edge("headings", "body", EdgeType.DEPENDENCY)

    # Body -> quality gate
    dag.add_edge("body", "qg_footnote_integrity", EdgeType.QUALITY_GATE)

    # Quality gate -> special sections
    dag.add_edge("qg_footnote_integrity", "special", EdgeType.DEPENDENCY)

    # Special -> cleanup chain (sequential)
    dag.add_edge("special", "cleanup_6a", EdgeType.DEPENDENCY)
    dag.add_edge("cleanup_6a", "cleanup_6b", EdgeType.DEPENDENCY)
    dag.add_edge("cleanup_6b", "cleanup_6c", EdgeType.DEPENDENCY)

    # Cleanup -> dramatis personae -> post-cleanup quality gate
    dag.add_edge("cleanup_6c", "cleanup_6d_dramatis", EdgeType.DEPENDENCY)
    dag.add_edge("cleanup_6d_dramatis", "qg_post_cleanup", EdgeType.QUALITY_GATE)

    # Post-cleanup -> validation -> epub
    dag.add_edge("qg_post_cleanup", "validation", EdgeType.DEPENDENCY)
    dag.add_edge("validation", "epub_build", EdgeType.DEPENDENCY)
    dag.add_edge("epub_build", "send_kindle", EdgeType.DEPENDENCY)

    return dag


def create_v1_pipeline_dag() -> DAGDefinition:
    """
    Create the V1 (linear) translation pipeline DAG.

    This is the original 7-stage sequential pipeline for comparison/fallback.
    """
    dag = DAGDefinition()

    stages = [
        ("metadata", "Metadata Translation", "tag", "#9C27B0"),
        ("toc", "TOC Translation", "list", "#00BCD4"),
        ("headings", "Headings Translation", "heading", "#FF9800"),
        ("body", "Body Translation", "book", "#2196F3"),
        ("special", "Special Sections", "star", "#795548"),
        ("cleanup", "Footnote Cleanup", "eraser", "#E91E63"),
        ("validation", "Final Validation", "check-circle", "#4CAF50"),
    ]

    for sid, name, icon, color in stages:
        dag.add_node(DAGNode(
            id=sid,
            display_name=name,
            node_type=NodeType.TASK,
            metadata={"icon": icon, "color": color},
        ))

    # Linear chain
    for i in range(len(stages) - 1):
        dag.add_edge(stages[i][0], stages[i + 1][0], EdgeType.DEPENDENCY)

    return dag
