import pytest

from ascent import sheets


@pytest.mark.parametrize("ref,pid", [
    ("https://codeforces.com/problemset/problem/1903/C", "CF:1903C"),
    ("https://codeforces.com/contest/1903/problem/C", "CF:1903C"),
    ("codeforces.com/contest/1873/problem/F2", "CF:1873F2"),
    ("1903c", "CF:1903C"),
    ("https://leetcode.com/problems/two-sum/description/", "LC:two-sum"),
    ("https://www.geeksforgeeks.org/problems/x/1", "EXT:https://www.geeksforgeeks.org/problems/x/1"),
])
def test_to_pid(ref, pid):
    assert sheets.to_pid(ref)[0] == pid


def test_bad_ref():
    with pytest.raises(ValueError):
        sheets.to_pid("not a problem")


def test_parse_lines_with_sections():
    items = sheets.parse("# Arrays\n1903C\nhttps://leetcode.com/problems/two-sum/\n# Graphs\n1873F2\n")
    assert [i["section"] for i in items] == ["Arrays", "Arrays", "Graphs"]


def test_parse_csv():
    items = sheets.parse("url,title,section\nhttps://codeforces.com/contest/1903/problem/C,Foo,1400\n")
    assert items == [{"pid": "CF:1903C", "url": "https://codeforces.com/problemset/problem/1903/C",
                      "title": "Foo", "section": "1400"}]
