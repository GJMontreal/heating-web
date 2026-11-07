import sqlite3

import pytest

from heating_web.history import RAW_RETENTION, WINDOW_RETENTION, WINDOW_SECONDS, History

NOW = 1_800_000_000 - (1_800_000_000 % WINDOW_SECONDS)


@pytest.fixture
def history(tmp_path):
  opened = History(str(tmp_path / "h.sqlite3"))
  yield opened
  try:
    opened.close()
  except sqlite3.ProgrammingError:
    pass


def rows(history, sql):
  return history.connection.execute(sql).fetchall()


def test_the_database_uses_wal_and_normal_synchronous(history):
  assert rows(history, "PRAGMA journal_mode") == [("wal",)]
  assert rows(history, "PRAGMA synchronous") == [(1,)]


def test_a_sample_is_stored_with_only_the_values_given(history):
  history.add(NOW, "Bedrooms", temp=19.5, ctl=0.4, hc=1)

  assert rows(history, "SELECT temp, target, mode, ctl, hc, boost, sh_ctl, sh_state FROM samples") == [
    (19.5, None, None, 0.4, 1, None, None, None)]


def test_a_zone_name_is_stored_once(history):
  history.add(NOW, "Bedrooms", ctl=0.1)
  history.add(NOW + 10, "Bedrooms", ctl=0.2)
  history.add(NOW, "Kitchen", ctl=0.3)

  assert rows(history, "SELECT name FROM zones ORDER BY id") == [("Bedrooms",), ("Kitchen",)]


def test_an_uncommitted_sample_is_invisible_to_another_connection(history, tmp_path):
  history.add(NOW, "Bedrooms", ctl=0.1)
  reader = sqlite3.connect(str(tmp_path / "h.sqlite3"))

  assert reader.execute("SELECT count(*) FROM samples").fetchone() == (0,)
  history.commit()
  assert reader.execute("SELECT count(*) FROM samples").fetchone() == (1,)
  reader.close()


def add_window(history, start, controls, shadows=None, hcs=None, states=None):
  for index, control in enumerate(controls):
    history.add(start + index * 10, "Bedrooms", temp=18.0 + index, target=21.0, ctl=control,
                sh_ctl=None if shadows is None else shadows[index],
                hc=None if hcs is None else hcs[index], sh_state=None if states is None else states[index])


def test_a_closed_window_becomes_one_row_of_means(history):
  add_window(history, NOW - WINDOW_SECONDS, [0.2, 0.4, 0.6], shadows=[0.1, 0.1, 0.4], hcs=[0, 1, 1], states=[0, 0, 1])

  history.aggregate(NOW)

  assert rows(history, "SELECT start, n, temp, target, ctl, sh_ctl, on_fraction, sh_on_fraction FROM windows") == [
    (NOW - WINDOW_SECONDS, 3, 19.0, 21.0, pytest.approx(0.4), pytest.approx(0.2), pytest.approx(2 / 3), pytest.approx(1 / 3))]


def test_the_open_window_is_not_aggregated(history):
  add_window(history, NOW, [0.2, 0.4])

  history.aggregate(NOW + 30)

  assert rows(history, "SELECT count(*) FROM windows") == [(0,)]


def test_aggregating_twice_gives_the_same_rows(history):
  add_window(history, NOW - WINDOW_SECONDS, [0.2, 0.4])

  history.aggregate(NOW)
  history.aggregate(NOW + 60)

  assert rows(history, "SELECT count(*) FROM windows") == [(1,)]


def test_each_zone_gets_its_own_window_row(history):
  history.add(NOW - 100, "Bedrooms", ctl=0.2)
  history.add(NOW - 100, "Kitchen", ctl=0.8)

  history.aggregate(NOW)

  assert rows(history, "SELECT count(*) FROM windows") == [(2,)]


def test_windows_fill_in_after_a_gap(history):
  add_window(history, NOW - 3 * WINDOW_SECONDS, [0.2])
  history.aggregate(NOW - 2 * WINDOW_SECONDS)
  add_window(history, NOW - WINDOW_SECONDS, [0.6])

  history.aggregate(NOW)

  assert [row[0] for row in rows(history, "SELECT start FROM windows ORDER BY start")] == [
    NOW - 3 * WINDOW_SECONDS, NOW - WINDOW_SECONDS]


def test_raw_samples_expire_after_seven_days_and_windows_after_fourteen(history):
  history.add(NOW - RAW_RETENTION - 10, "Bedrooms", ctl=0.1)
  history.add(NOW - RAW_RETENTION + 10, "Bedrooms", ctl=0.2)
  history.aggregate(NOW - RAW_RETENTION + 100)
  history.aggregate(NOW)
  history.connection.execute("INSERT INTO windows (zone, start, n) VALUES (1, ?, 1)", (NOW - WINDOW_RETENTION - 10,))
  history.connection.execute("INSERT INTO windows (zone, start, n) VALUES (1, ?, 1)", (NOW - WINDOW_RETENTION + 10,))

  history.prune(NOW)

  assert [row[0] for row in rows(history, "SELECT ts FROM samples")] == [NOW - RAW_RETENTION + 10]
  starts = [row[0] for row in rows(history, "SELECT start FROM windows")]
  assert NOW - WINDOW_RETENTION - 10 not in starts
  assert NOW - WINDOW_RETENTION + 10 in starts


def test_windows_outlive_the_raw_samples_they_came_from(history):
  add_window(history, NOW - RAW_RETENTION - WINDOW_SECONDS, [0.5])
  history.aggregate(NOW - RAW_RETENTION)

  history.prune(NOW)

  assert rows(history, "SELECT count(*) FROM samples") == [(0,)]
  assert rows(history, "SELECT count(*) FROM windows") == [(1,)]


def test_reopening_keeps_the_data_and_the_zone_ids(tmp_path):
  path = str(tmp_path / "h.sqlite3")
  first = History(path)
  first.add(NOW, "Bedrooms", ctl=0.1)
  first.close()

  second = History(path)
  second.add(NOW + 10, "Bedrooms", ctl=0.2)
  second.close()

  check = sqlite3.connect(path)
  assert check.execute("SELECT count(*), count(DISTINCT zone) FROM samples").fetchone() == (2, 1)
  check.close()
