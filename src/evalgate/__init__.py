"""evalgate: evals as a release gate."""

from .cases import Case, Suite, SuiteError, load_suite
from .compare import GateError, check_gate, compare
from .runner import AgentResult, run_suite
from .scorers import register_scorer

__version__ = "0.1.0"
__all__ = [
    "AgentResult", "Case", "GateError", "Suite", "SuiteError", "check_gate", "compare",
    "load_suite", "register_scorer", "run_suite",
]
