def compute_status(operstatus, optical_rx_dbm=None, signal_warn_threshold_dbm=None, error_count=None):
    """Returns 'up' | 'warn' | 'down' | 'unknown'.

    operstatus follows IF-MIB ifOperStatus convention: 1 = up, anything
    else (2 = down, etc.) = down. None means no data was collected (stale
    cache or missing item) and must resolve to 'unknown', never a stale
    'up'.
    """
    if operstatus is None:
        return 'unknown'
    if operstatus != 1:
        return 'down'
    if signal_warn_threshold_dbm is not None and optical_rx_dbm is not None:
        if optical_rx_dbm < signal_warn_threshold_dbm:
            return 'warn'
    if error_count is not None and error_count > 0:
        return 'warn'
    return 'up'
