from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from itertools import combinations
from typing import Iterable


@dataclass(frozen=True)
class Employee:
    id: int
    name: str
    weekday_shift: str = "08h–18h"
    weekend_shift: str = "08h–18h"
    rotation_order: int = 0
    group_type: str = "GERAL"  # GERAL or N2


@dataclass(frozen=True)
class DayAssignment:
    employee_id: int
    work_date: date
    status: str  # T or F
    shift: str | None
    note: str | None = None


class ScheduleGenerationError(ValueError):
    pass


def shift_bucket(shift: str) -> str:
    text = (shift or "").lower()
    return "NOITE" if any(token in text for token in ("18h", "19h", "20h", "21h", "22h")) else "MANHA"


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _week_mondays(start: date, end: date) -> list[date]:
    cursor = monday_of(start)
    last = monday_of(end)
    result: list[date] = []
    while cursor <= last:
        result.append(cursor)
        cursor += timedelta(days=7)
    return result


def _choose_regular_weekend(
    regular: list[Employee],
    week_index: int,
    stats: dict[int, dict[str, int | str]],
) -> tuple[int, set[int], set[int]]:
    """Choose one full-weekend-off worker and split the rest across Sat/Sun.

    The score mirrors the production prototype priorities: shift balance first,
    then rotation/fairness and avoidance of repeatedly assigning the same day.
    """
    eligible = [e for e in regular if int(stats[e.id]["sunday_streak"]) >= 2]
    pool = eligible or regular
    full_weekend = min(
        pool,
        key=lambda e: (
            int(stats[e.id]["fds"]),
            -int(stats[e.id]["sunday_streak"]),
            int(stats[e.id]["sat"]) + int(stats[e.id]["sun"]),
            (e.rotation_order - week_index) % len(regular),
        ),
    )

    available = [e for e in regular if e.id != full_weekend.id]
    half = len(available) // 2
    best: tuple[tuple, set[int]] | None = None

    for sunday_tuple in combinations(available, half):
        sunday_ids = {e.id for e in sunday_tuple}
        saturday = [e for e in available if e.id not in sunday_ids]
        buckets = {shift_bucket(e.weekend_shift) for e in available}
        shift_gap = sum(
            abs(
                sum(shift_bucket(e.weekend_shift) == bucket for e in sunday_tuple)
                - sum(shift_bucket(e.weekend_shift) == bucket for e in saturday)
            )
            for bucket in buckets
        )
        pipeline_penalty = 0 if any(int(stats[e.id]["sunday_streak"]) >= 1 for e in sunday_tuple) else 1
        fairness = sum(
            abs(
                (int(stats[e.id]["sun"]) + int(e.id in sunday_ids))
                - (int(stats[e.id]["sat"]) + int(e.id not in sunday_ids))
            )
            for e in available
        )
        repeats = sum(stats[e.id]["previous"] == ("DOM" if e.id in sunday_ids else "SAB") for e in available)
        long_sundays = sum(max(0, int(stats[e.id]["sunday_streak"]) - 1) for e in sunday_tuple)
        score = (shift_gap, pipeline_penalty, fairness, repeats, long_sundays, tuple(sorted(sunday_ids)))
        if best is None or score < best[0]:
            best = (score, sunday_ids)

    assert best is not None
    sunday_ids = best[1]
    saturday_ids = {e.id for e in available if e.id not in sunday_ids}
    return full_weekend.id, saturday_ids, sunday_ids


def _choose_weekday_off(
    employee: Employee,
    week: date,
    n2_saturday: set[int],
    n2_sunday: set[int],
    regular_full_weekend: int,
    regular_saturday: set[int],
    regular_sunday: set[int],
    preferred: int,
    starting_streak: int,
    off_counts: list[int],
    off_by_shift: list[dict[str, int]],
) -> tuple[int, int]:
    del regular_full_weekend
    options: list[tuple] = []

    for weekday_off in range(5):
        streak = starting_streak
        maximum = 0
        for offset in range(7):
            day = week + timedelta(days=offset)
            dow = day.weekday()
            if employee.group_type == "N2":
                works = (
                    (dow < 5 and dow != weekday_off)
                    or (dow == 5 and employee.id in n2_saturday)
                    or (dow == 6 and employee.id in n2_sunday)
                )
            else:
                works = (
                    (dow < 5 and dow != weekday_off)
                    or (dow == 5 and employee.id in regular_saturday)
                    or (dow == 6 and employee.id in regular_sunday)
                )
            streak = streak + 1 if works else 0
            maximum = max(maximum, streak)

        distance = min((weekday_off - preferred) % 5, (preferred - weekday_off) % 5)
        bucket = shift_bucket(employee.weekday_shift)
        options.append(
            (
                maximum > 6,
                off_counts[weekday_off] >= 3,
                maximum,
                off_counts[weekday_off],
                off_by_shift[weekday_off][bucket],
                distance,
                weekday_off,
                streak,
            )
        )

    selected = min(options)
    return int(selected[6]), int(selected[7])


def generate_schedule(
    employees: Iterable[Employee],
    start: date,
    end: date,
    *,
    rotation_cursor: int = 0,
    work_streak_before: dict[int, int] | None = None,
    weekend_history: dict[int, dict[str, int | str]] | None = None,
) -> tuple[list[DayAssignment], dict]:
    if end < start:
        raise ScheduleGenerationError("The end date must be on or after the start date.")

    team = sorted(list(employees), key=lambda e: (e.rotation_order, e.id))
    n2 = [e for e in team if e.group_type == "N2"]
    regular = [e for e in team if e.group_type != "N2"]

    if len(n2) < 2:
        raise ScheduleGenerationError("At least two active N2 employees are required.")
    if len(regular) < 3:
        raise ScheduleGenerationError("At least three general-team employees are required.")
    if (len(regular) - 1) % 2:
        raise ScheduleGenerationError(
            "The general team cannot be split evenly between Saturday and Sunday after assigning one full weekend off."
        )

    weeks = _week_mondays(start, end)
    streaks = {e.id: int((work_streak_before or {}).get(e.id, 0)) for e in team}
    stats: dict[int, dict[str, int | str]] = {}
    for e in regular:
        supplied = (weekend_history or {}).get(e.id, {})
        stats[e.id] = {
            "sat": int(supplied.get("sat", 0)),
            "sun": int(supplied.get("sun", 0)),
            "sunday_streak": int(supplied.get("sunday_streak", 0)),
            "fds": int(supplied.get("fds", 0)),
            "previous": str(supplied.get("previous", "FDS")),
        }

    n2_weekends: dict[date, tuple[set[int], set[int]]] = {}
    regular_weekends: dict[date, tuple[int, set[int], set[int]]] = {}
    cursor = rotation_cursor % len(n2)

    for week_index, week in enumerate(weeks):
        ordered = n2[cursor:] + n2[:cursor]
        saturday_n2 = {ordered[0].id}
        sunday_n2 = {ordered[1].id}
        cursor = (cursor + 2) % len(n2)
        n2_weekends[week] = (saturday_n2, sunday_n2)

        fds, sat_ids, sun_ids = _choose_regular_weekend(regular, week_index, stats)
        regular_weekends[week] = (fds, sat_ids, sun_ids)

        for employee in regular:
            state = stats[employee.id]
            if employee.id == fds:
                state["previous"] = "FDS"
                state["sunday_streak"] = 0
                state["fds"] = int(state["fds"]) + 1
            elif employee.id in sun_ids:
                state["previous"] = "DOM"
                state["sunday_streak"] = int(state["sunday_streak"]) + 1
                state["sun"] = int(state["sun"]) + 1
            else:
                state["previous"] = "SAB"
                state["sunday_streak"] = 0
                state["sat"] = int(state["sat"]) + 1

    weekday_offs: dict[tuple[date, int], int | None] = {}
    for week_index, week in enumerate(weeks):
        n2_sat, n2_sun = n2_weekends[week]
        fds, regular_sat, regular_sun = regular_weekends[week]
        n2_weekend_workers = n2_sat | n2_sun

        off_counts = [0, 0, 0, 0, 0]
        off_by_shift = [{"MANHA": 0, "NOITE": 0} for _ in range(5)]

        for employee in team:
            fixed = (
                (employee.group_type == "N2" and employee.id not in n2_weekend_workers)
                or (employee.group_type != "N2" and employee.id == fds)
            )
            if fixed:
                weekday_offs[(week, employee.id)] = None
                continue

            preferred = (week_index + team.index(employee)) % 5
            weekday_off, ending_streak = _choose_weekday_off(
                employee,
                week,
                n2_sat,
                n2_sun,
                fds,
                regular_sat,
                regular_sun,
                preferred,
                streaks[employee.id],
                off_counts,
                off_by_shift,
            )
            weekday_offs[(week, employee.id)] = weekday_off
            off_counts[weekday_off] += 1
            off_by_shift[weekday_off][shift_bucket(employee.weekday_shift)] += 1
            streaks[employee.id] = ending_streak

    assignments: list[DayAssignment] = []
    day = start
    while day <= end:
        week = monday_of(day)
        n2_sat, n2_sun = n2_weekends[week]
        fds, regular_sat, regular_sun = regular_weekends[week]
        dow = day.weekday()

        for employee in team:
            weekday_off = weekday_offs[(week, employee.id)]
            note: str | None = None
            if employee.group_type == "N2":
                works = (
                    (dow < 5 and (weekday_off is None or dow != weekday_off))
                    or (dow == 5 and employee.id in n2_sat)
                    or (dow == 6 and employee.id in n2_sun)
                )
                if dow == 5 and employee.id in n2_sat:
                    note = "N2 Saturday duty"
                elif dow == 6 and employee.id in n2_sun:
                    note = "N2 Sunday duty"
            else:
                if employee.id == fds:
                    works = dow < 5
                    if dow >= 5:
                        note = "Full weekend off by rotation"
                else:
                    works = (
                        (dow < 5 and dow != weekday_off)
                        or (dow == 5 and employee.id in regular_sat)
                        or (dow == 6 and employee.id in regular_sun)
                    )
                    if dow >= 5 and works:
                        note = "Balanced weekend coverage"

            assignments.append(
                DayAssignment(
                    employee_id=employee.id,
                    work_date=day,
                    status="T" if works else "F",
                    shift=(employee.weekend_shift if dow >= 5 else employee.weekday_shift) if works else None,
                    note=note,
                )
            )
        day += timedelta(days=1)

    _validate(team, assignments, weeks, start, end, work_streak_before or {})

    metadata = {
        "rotation_cursor": cursor,
        "weeks": [
            {
                "monday": week.isoformat(),
                "n2_saturday": sorted(n2_weekends[week][0]),
                "n2_sunday": sorted(n2_weekends[week][1]),
                "general_full_weekend_off": regular_weekends[week][0],
                "general_saturday": sorted(regular_weekends[week][1]),
                "general_sunday": sorted(regular_weekends[week][2]),
            }
            for week in weeks
        ],
    }
    return assignments, metadata


def _validate(
    employees: list[Employee],
    assignments: list[DayAssignment],
    weeks: list[date],
    start: date,
    end: date,
    starting_streaks: dict[int, int],
) -> None:
    by_key = {(a.employee_id, a.work_date): a for a in assignments}
    errors: list[str] = []

    for employee in employees:
        streak = int(starting_streaks.get(employee.id, 0))
        day = start
        while day <= end:
            current = by_key[(employee.id, day)]
            streak = streak + 1 if current.status == "T" else 0
            if streak > 6:
                errors.append(f"{employee.name} exceeds six consecutive work days on {day.isoformat()}")
                break
            day += timedelta(days=1)

    for week in weeks:
        week_end = week + timedelta(days=6)
        if week < start or week_end > end:
            continue
        for employee in employees:
            worked = sum(
                by_key[(employee.id, week + timedelta(days=offset))].status == "T"
                for offset in range(7)
            )
            if worked != 5:
                errors.append(f"{employee.name} works {worked} days in week {week.isoformat()}")

    if errors:
        raise ScheduleGenerationError("; ".join(errors[:12]))
