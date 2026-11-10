"""Read-only service adapters; authentication is supplied by the caller."""

from .spotify import SpotifyClient, SpotifyPlayback
from .teams import TeamsPresence, TeamsPresenceClient
from .token_store import KeyringTokenStore

__all__ = [
	"KeyringTokenStore",
	"SpotifyClient",
	"SpotifyPlayback",
	"TeamsPresence",
	"TeamsPresenceClient",
]