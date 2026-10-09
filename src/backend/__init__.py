"""Backend integration layer for Supabase/Baserow."""

from .supabase_client import SupabaseClient, SupabaseError
from .auth_service import AuthService, AuthSession
from .entitlement_service import EntitlementService, Entitlement
from .transcription_repo import TranscriptionRepo
from .settings_repo import SettingsRepo
from .support_repo import SupportRepo
from .sync_worker import SyncWorker
from .edge_transcribe_service import EdgeTranscribeService, EdgeTranscribeResult
from .billing_service import BillingService, BillingError, PortalSession

__all__ = [
    "SupabaseClient",
    "SupabaseError",
    "AuthService",
    "AuthSession",
    "EntitlementService",
    "Entitlement",
    "TranscriptionRepo",
    "SettingsRepo",
    "SupportRepo",
    "SyncWorker",
    "EdgeTranscribeService",
    "EdgeTranscribeResult",
    "BillingService",
    "BillingError",
    "PortalSession",
]
