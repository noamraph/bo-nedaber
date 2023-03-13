from __future__ import annotations

import pytest

from bo_nedaber.bo_nedaber import CON, FEMALE, MALE, PRO, adjust_element, adjust_str


def test_adjust_element() -> None:
    assert adjust_element("A|B", MALE, PRO) == "A"
    assert adjust_element("A|B", MALE, CON) == "B"
    assert adjust_element("|B", MALE, PRO) == ""
    assert adjust_element("A/B", FEMALE, PRO) == "B"
    assert adjust_element("A/B", MALE, PRO) == "A"
    assert adjust_element("A/B|C/D", MALE, PRO) == "A"
    assert adjust_element("A/B|C/D", FEMALE, PRO) == "B"
    assert adjust_element("A/B|C/D", MALE, CON) == "C"
    assert adjust_element("A/B|C/D", FEMALE, CON) == "D"
    with pytest.raises(ValueError):
        adjust_element("AB", MALE, PRO)
    with pytest.raises(ValueError):
        adjust_element("A|B|C", MALE, PRO)
    with pytest.raises(ValueError):
        adjust_element("A/B/C", MALE, PRO)
    with pytest.raises(ValueError):
        adjust_element("A/B|C", MALE, PRO)


def test_adjust_str() -> None:
    s = "אני [תומך/תומכת|מתנגד/מתנגדת] רפורמה נלהב[/ת]"
    assert adjust_str(s, MALE, PRO) == "אני תומך רפורמה נלהב"
    assert adjust_str(s, MALE, CON) == "אני מתנגד רפורמה נלהב"
    assert adjust_str(s, FEMALE, PRO) == "אני תומכת רפורמה נלהבת"
    assert adjust_str(s, FEMALE, CON) == "אני מתנגדת רפורמה נלהבת"
