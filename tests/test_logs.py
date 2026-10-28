from exorcist.logs import parse_line, normalize, signature, load_scenario, interesting


def test_parse_bracket_format():
    e = parse_line("[2026-10-28 02:01:15.002] [ERROR] [ur_robot_driver]: C204A0: Protective Stop: Position deviates from path. Joint 3 deviation 0.052 rad", "ur5e")
    assert e.level == "ERROR" and e.source == "ur_robot_driver" and e.code == "C204A0" and e.system == "ur5e"


def test_parse_ros_console_format():
    e = parse_line("[WARN] [1793530923.118] [tf2_buffer]: Warning: TF_REPEATED_DATA ignoring data", "amr")
    assert e.level == "WARN" and e.source == "tf2_buffer" and e.code == "TF_REPEATED_DATA"


def test_normalize_collapses_numbers():
    a = normalize("Joint 3 position deviation 0.052 rad exceeds 0.040 rad limit at 0x21 /dev/ttyUSB0")
    b = normalize("Joint 3 position deviation 0.071 rad exceeds 0.040 rad limit at 0x3f /dev/ttyUSB1")
    assert a == b


def test_scenario_loads_sorted_and_filters():
    robot, events = load_scenario("samples/haunted_cell")
    assert robot["systems"][0]["id"] == "ur5e"
    assert events == sorted(events, key=lambda e: e.ts)
    sigs = {signature(e) for e in interesting(events)}
    assert 8 <= len(sigs) <= 20
