"""CLEAR Controller V2 package.

The V2 controller is intentionally isolated from the legacy decision/rewrite loop.
Only ActionArbitrator may eventually own the final executed_action.
"""
