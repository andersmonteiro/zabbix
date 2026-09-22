from status import compute_status


def test_compute_status_unknown_when_no_data():
    assert compute_status(operstatus=None) == 'unknown'


def test_compute_status_down_when_operstatus_not_up():
    assert compute_status(operstatus=2) == 'down'


def test_compute_status_up_when_healthy():
    assert compute_status(
        operstatus=1, optical_rx_dbm=-19.0, signal_warn_threshold_dbm=-25.0
    ) == 'up'


def test_compute_status_warn_when_signal_below_threshold():
    assert compute_status(
        operstatus=1, optical_rx_dbm=-27.0, signal_warn_threshold_dbm=-25.0
    ) == 'warn'


def test_compute_status_ignores_threshold_when_not_configured():
    assert compute_status(
        operstatus=1, optical_rx_dbm=-40.0, signal_warn_threshold_dbm=None
    ) == 'up'


def test_compute_status_warn_when_errors_present():
    assert compute_status(operstatus=1, error_count=5) == 'warn'


def test_compute_status_up_when_no_errors():
    assert compute_status(operstatus=1, error_count=0) == 'up'
