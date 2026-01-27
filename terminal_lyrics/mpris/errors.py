class MprisError(RuntimeError):
    pass


class NoPlayersFound(MprisError):
    pass


class PlayerUnavailable(MprisError):
    pass

