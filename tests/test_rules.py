import unittest

from ibuddy.rules import classify


class ClassifyTest(unittest.TestCase):
    def test_permission_prompts_are_waiting(self):
        self.assertEqual(classify("Allow Claude to run python script.py?"), "waiting")
        self.assertEqual(classify("allow claude to write settings.json?"), "waiting")

    def test_input_prompts_are_waiting(self):
        self.assertEqual(classify("Project X Claude is waiting for your input"), "waiting")
        self.assertEqual(classify("Aguardando sua aprovação"), "waiting")   # Portuguese keyword

    def test_scheduled_tasks_are_ignored(self):
        self.assertEqual(classify("Scheduled task completed Morning brief"), "ignore")

    def test_anything_else_is_a_finished_response(self):
        self.assertEqual(classify("Contract summary ready"), "done")
        self.assertEqual(classify("Resumo do contrato pronto"), "done")
        self.assertEqual(classify(""), "done")
        self.assertEqual(classify(None), "done")

    def test_ignore_wins_over_waiting(self):
        self.assertEqual(classify("Scheduled task waiting for your input"), "ignore")


if __name__ == "__main__":
    unittest.main()
