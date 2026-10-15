import tempfile
import os
import sys
import unittest

class TestConversion(unittest.TestCase):
    def test_freezing(self):
        # Test freezing point of water
        result = os.system('python main.py 0')
        self.assertEqual(result, 0)
    
    def test_boiling(self):
        # Test boiling point of water
        result = os.system('python main.py 100')
        self.assertEqual(result, 0)

if __name__ == '__main__':
    unittest.main()