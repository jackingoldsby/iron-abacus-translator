"""
Workflow Name Generator

Generates Docker-style random names for workflow templates.
Format: {adjective}_{scientist}

Examples: clever_turing, brave_curie, swift_euler
"""

import random


# Adjectives describing qualities/characteristics
ADJECTIVES = [
    "clever", "swift", "brave", "patient", "wise", "eager",
    "diligent", "precise", "thorough", "creative", "elegant",
    "efficient", "robust", "nimble", "focused", "steadfast",
    "brilliant", "astute", "shrewd", "keen", "adept",
    "skilled", "deft", "agile", "sharp", "bright",
    "quick", "alert", "smart", "wise", "sage",
    "learned", "savvy", "crafty", "wily", "artful"
]

# Famous scientists, mathematicians, and computer scientists
SCIENTISTS = [
    # Computer Science
    "turing", "lovelace", "hopper", "babbage", "knuth",
    "dijkstra", "neumann", "shannon", "boole", "church",
    "kleene", "mccarthy", "ritchie", "thompson", "kernighan",

    # Mathematics
    "euler", "gauss", "riemann", "cantor", "hilbert",
    "godel", "poincare", "fermat", "pascal", "leibniz",
    "fibonacci", "pythagoras", "archimedes", "euclid",

    # Physics
    "einstein", "feynman", "hawking", "newton", "galileo",
    "kepler", "planck", "bohr", "heisenberg", "schrodinger",
    "maxwell", "faraday", "tesla", "curie", "rutherford",

    # Biology/Chemistry
    "darwin", "mendel", "pasteur", "fleming", "nobel",
    "lavoisier", "dalton", "mendeleev", "avogadro",

    # Other Sciences
    "sagan", "tyson", "hubble", "copernicus", "brahe"
]


def generate_workflow_id() -> str:
    """
    Generate a random Docker-style workflow ID.

    Returns:
        str: Workflow ID in format {adjective}_{scientist}, e.g., "clever_turing"

    Examples:
        >>> generate_workflow_id()
        'brave_curie'
        >>> generate_workflow_id()
        'swift_euler'
    """
    adjective = random.choice(ADJECTIVES)
    scientist = random.choice(SCIENTISTS)
    return f"{adjective}_{scientist}"


def generate_unique_workflow_id(existing_ids: set) -> str:
    """
    Generate a unique workflow ID that doesn't conflict with existing IDs.

    Args:
        existing_ids: Set of existing workflow IDs to avoid

    Returns:
        str: Unique workflow ID

    Raises:
        ValueError: If unable to generate unique ID after 100 attempts
    """
    max_attempts = 100
    for _ in range(max_attempts):
        workflow_id = generate_workflow_id()
        if workflow_id not in existing_ids:
            return workflow_id

    # Fallback: add random suffix
    base_id = generate_workflow_id()
    suffix = random.randint(1000, 9999)
    return f"{base_id}_{suffix}"


def parse_workflow_id(workflow_id: str) -> dict:
    """
    Parse a workflow ID into its components.

    Args:
        workflow_id: Workflow ID string

    Returns:
        dict: Dictionary with 'adjective' and 'scientist' keys

    Examples:
        >>> parse_workflow_id("clever_turing")
        {'adjective': 'clever', 'scientist': 'turing'}
    """
    parts = workflow_id.split('_', 1)
    if len(parts) == 2:
        return {
            'adjective': parts[0],
            'scientist': parts[1]
        }
    return {
        'adjective': '',
        'scientist': workflow_id
    }


def is_valid_workflow_id(workflow_id: str) -> bool:
    """
    Check if a workflow ID follows the expected format.

    Args:
        workflow_id: Workflow ID to validate

    Returns:
        bool: True if valid format
    """
    parts = parse_workflow_id(workflow_id)
    return (
        parts['adjective'] in ADJECTIVES and
        parts['scientist'] in SCIENTISTS
    )


if __name__ == "__main__":
    # Generate some example workflow IDs
    print("Example workflow IDs:")
    for _ in range(10):
        workflow_id = generate_workflow_id()
        parsed = parse_workflow_id(workflow_id)
        print(f"  {workflow_id:25} → {parsed['adjective']} + {parsed['scientist']}")
