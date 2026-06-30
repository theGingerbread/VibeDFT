"""Per-program validation rules for QE input files.

All validators take a ValidationContext and return lists of SanityIssue.
Actual logic lives in Python rule functions; YAML knowledge_base files
hold seed patterns and documentation.
"""

from vibedft.validators.two_d import analyze_2d_validity

__all__ = ["analyze_2d_validity"]
