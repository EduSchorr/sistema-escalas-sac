from datetime import date, timedelta
import unittest

from scheduler_engine import Employee, ScheduleGenerationError, generate_schedule


class SchedulerEngineTests(unittest.TestCase):
    def setUp(self):
        self.team = [
            Employee(1, "N2 Demo 01", "08h–18h", "10h–20h", 0, "N2"),
            Employee(2, "N2 Demo 02", "08h–18h", "10h–20h", 1, "N2"),
            Employee(3, "N2 Demo 03", "12h–22h", "10h–20h", 2, "N2"),
            Employee(4, "Agente Demo 01", "08h–18h", "08h–18h", 3, "GERAL"),
            Employee(5, "Agente Demo 02", "08h–18h", "08h–18h", 4, "GERAL"),
            Employee(6, "Agente Demo 03", "12h–22h", "12h–22h", 5, "GERAL"),
            Employee(7, "Agente Demo 04", "12h–22h", "12h–22h", 6, "GERAL"),
            Employee(8, "Agente Demo 05", "08h–18h", "08h–18h", 7, "GERAL"),
        ]

    def test_full_weeks_are_5x2(self):
        start = date(2026, 10, 5)
        end = start + timedelta(days=13)
        rows, metadata = generate_schedule(self.team, start, end)
        by_employee = {employee.id: [] for employee in self.team}
        for row in rows:
            by_employee[row.employee_id].append(row)
        for entries in by_employee.values():
            first = entries[:7]
            second = entries[7:14]
            self.assertEqual(sum(x.status == "T" for x in first), 5)
            self.assertEqual(sum(x.status == "T" for x in second), 5)
        self.assertEqual(len(metadata["weeks"]), 2)

    def test_n2_weekend_has_one_worker_per_day(self):
        start = date(2026, 10, 5)
        rows, _ = generate_schedule(self.team, start, start + timedelta(days=6))
        saturday = start + timedelta(days=5)
        sunday = start + timedelta(days=6)
        n2_ids = {1, 2, 3}
        sat = [x for x in rows if x.work_date == saturday and x.employee_id in n2_ids and x.status == "T"]
        sun = [x for x in rows if x.work_date == sunday and x.employee_id in n2_ids and x.status == "T"]
        self.assertEqual(len(sat), 1)
        self.assertEqual(len(sun), 1)

    def test_requires_valid_team_shape(self):
        with self.assertRaises(ScheduleGenerationError):
            generate_schedule(self.team[:4], date(2026, 10, 5), date(2026, 10, 11))


if __name__ == "__main__":
    unittest.main()
