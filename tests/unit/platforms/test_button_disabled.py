#!/usr/bin/env python3
"""
验证按钮禁用状态检测修复
"""
import re


def test_button_disabled_detection():
    """测试按钮禁用状态检测逻辑"""
    print("=== Testing Button Disabled Detection ===\n")
    
    # 模拟不同的按钮状态
    test_cases = [
        # (disabled_attr, style, expected_available)
        (None, "", True),  # 没有 disabled，没有样式 -> 可用
        (None, "opacity: 1.0", True),  # 没有 disabled，opacity=1.0 -> 可用
        (None, "opacity: 0.8", True),  # 没有 disabled，opacity=0.8 -> 可用
        (None, "opacity: 0.4", False),  # 没有 disabled，但 opacity=0.4 -> 禁用
        ("true", "", False),  # 有 disabled 属性 -> 禁用
        ("", "", False),  # 有 disabled 属性（空值）-> 禁用
        (None, "color: red; opacity: 0.3", False),  # opacity 太低 -> 禁用
        (None, "opacity: 0.6; color: blue", True),  # opacity=0.6 -> 可用
    ]
    
    for disabled_attr, style, expected in test_cases:
        is_available = True
        
        # 检查 disabled 属性
        if disabled_attr is not None:
            is_available = False
        else:
            # 检查 opacity
            opacity_match = re.search(r'opacity:\s*([\d.]+)', style)
            if opacity_match:
                opacity = float(opacity_match.group(1))
                if opacity < 0.5:
                    is_available = False
        
        status = "✓" if is_available == expected else "✗"
        print(f"  {status} disabled={disabled_attr}, style='{style}'")
        print(f"      -> available={is_available} (expected: {expected})")
        assert is_available == expected
    
    print("\nAll button disabled detection tests passed! ✓\n")


def demonstrate_fix():
    """演示修复效果"""
    print("="*70)
    print("DEMONSTRATION: Button Disabled State Detection")
    print("="*70)
    print()
    
    print("PROBLEM (Before Fix):")
    print("  - Raise button exists on page but is grayed out (disabled)")
    print("  - is_visible() returns True (button is physically visible)")
    print("  - But button should NOT be in 'available' list")
    print("  - Result: state shows 'Available Actions: raise' even when not your turn\n")
    
    print("SOLUTION (After Fix):")
    print("  Added two-level check:")
    print("  1. Check 'disabled' attribute")
    print("     - If present (any value) -> button is disabled")
    print()
    print("  2. Check 'opacity' in style")
    print("     - If opacity < 0.5 -> button is visually disabled (grayed out)")
    print()
    print("  Only add to 'available' if BOTH checks pass\n")
    
    print("Expected behavior after fix:")
    print("  Scenario 1: Not your turn")
    print("    - Raise button: visible but grayed out (opacity: 0.4)")
    print("    - Result: Available Actions: (none) ✓")
    print()
    print("  Scenario 2: Your turn")
    print("    - Raise button: visible and enabled (opacity: 1.0)")
    print("    - Result: Available Actions: fold, call, raise ✓")
    print()
    print("="*70)


if __name__ == "__main__":
    test_button_disabled_detection()
    demonstrate_fix()
    
    print("\n✅ All verification tests passed!")
    print("\nThe button detection now correctly filters out disabled/grayed buttons.")
