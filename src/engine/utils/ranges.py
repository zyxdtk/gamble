from __future__ import annotations
import os
import yaml
from typing import Dict, List


class RangeManager:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._ranges = None
            cls._instance._load_ranges()
        return cls._instance
    
    def _load_ranges(self) -> None:
        self._ranges = self._load_from_yaml()
        if not self._ranges:
            self._ranges = self._get_fallback_ranges()
    
    def _load_from_yaml(self) -> Dict[str, List[str]]:
        config_path = os.path.join(os.getcwd(), "config", "preflop_ranges.yaml")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    return data.get("ranges", {})
            except Exception:
                pass
        return {}
    
    def _get_fallback_ranges(self) -> Dict[str, List[str]]:
        base_range = [
            "AA", "KK", "QQ", "JJ", "TT", "99", "88", "77",
            "AKs", "AQs", "AJs", "ATs", "KQs", "KJs", "QJs", "JTs",
            "AKo", "AQo", "AJo"
        ]
        return {
            "EP": base_range[:10],
            "MP": base_range[:15],
            "LP": base_range,
            "SB": base_range,
            "BB": base_range,
            "ALL": base_range
        }
    
    def get_range(self, position: str) -> List[str]:
        return self._ranges.get(position, self._ranges.get("ALL", []))
    
    def is_hand_in_range(self, hand_str: str, position: str) -> bool:
        return hand_str in self.get_range(position)
    
    def get_hand_tier(self, hand_str: str) -> int:
        tier1 = ["AA", "KK", "QQ", "JJ", "AKs", "AKo"]
        tier2 = ["TT", "99", "AQs", "AQo", "AJs", "KQs"]
        tier3 = ["88", "77", "ATs", "KJs", "QJs", "JTs", "T9s"]
        
        if hand_str in tier1:
            return 1
        if hand_str in tier2:
            return 2
        if hand_str in tier3:
            return 3
        return 4
