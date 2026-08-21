from __future__ import annotations
from dataclasses import dataclass

@dataclass
class LiveState:
    position:int=0
    last_signal_second:int|None=None
    strategy_version:str="UNFROZEN"

class SharedStateEngine:
    """State container intentionally shared by replay/paper/live adapters."""
    def __init__(self,state:LiveState|None=None): self.state=state or LiveState()
    def can_enter(self)->bool: return self.state.position==0
    def on_entry(self):
        if not self.can_enter(): raise RuntimeError("one-position invariant violated")
        self.state.position=1
    def on_exit(self): self.state.position=0
