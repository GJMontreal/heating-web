from heating_web import contract


def test_the_contract_values_match_the_control_service():
  assert contract.ACTIVE == "active"
  assert contract.SHADOW == "shadow"
  assert contract.TIME_FORMAT == "%Y-%m-%dT%H:%M:%SZ"
  assert contract.STALE_AFTER == 7200
  assert contract.CONTROL_VALUE == "control_value"
