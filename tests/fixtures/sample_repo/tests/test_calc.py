import unittest

from calc import clamp, first_n


class TestFirstN(unittest.TestCase):
    def test_first_two(self):
        self.assertEqual(first_n([1, 2, 3], 2), [1, 2])

    def test_first_zero(self):
        self.assertEqual(first_n([1, 2, 3], 0), [])

    def test_all(self):
        self.assertEqual(first_n([1, 2, 3], 3), [1, 2, 3])


class TestClamp(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(clamp(5, 0, 3), 3)
        self.assertEqual(clamp(-1, 0, 3), 0)


if __name__ == "__main__":
    unittest.main()
