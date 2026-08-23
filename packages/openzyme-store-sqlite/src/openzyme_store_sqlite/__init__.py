"""SQLite Control Store Adapter public surface."""

from .authority_mapping import *  # noqa: F403
from .authority_mapping import __all__ as _authority_mapping_exports
from .adapter import SQLITE_STORE_ADAPTER_CONTRACT_DIGEST
from .adapter import SQLITE_STORE_CONFIGURATION_SCHEMA_DIGEST
from .adapter import SQLITE_STORE_PREFLIGHT_CONTRACT_DIGEST
from .adapter import SQLiteConnectionProvider
from .adapter import SQLiteStoreAdapterError
from .adapter import SQLiteStoreConfiguration
from .adapter import SQLiteStorePreflightObservation
from .control_store import SQLiteControlStore
from .control_store import SQLiteControlStoreError
from .control_store import SQLiteKernelEntityCodec
from .control_store import SQLiteKernelUnitOfWork
from .deployment_proof import DEPLOYMENT_SCHEMA_STATE_SCHEMA_VERSION
from .deployment_proof import FRESH_INSTALL_BOOTSTRAP_RECEIPT_SCHEMA_VERSION
from .deployment_proof import DeploymentProofVariant
from .deployment_proof import FreshInstallBootstrapReceiptV2
from .deployment_proof import FreshInstallCompositionSeed
from .deployment_proof import FreshInstallDeploymentProof
from .deployment_proof import MigrationSourceIdentity
from .deployment_proof import SQLiteDeploymentProofError
from .deployment_proof import seed_fresh_install_composition_offline
from .deployment_proof import verify_fresh_install_deployment_read_only
from .device_fresh_reset import DeviceFreshResetError
from .device_fresh_reset import INVENTORY_SCHEMA as DEVICE_RESET_INVENTORY_SCHEMA
from .device_fresh_reset import RECEIPT_SCHEMA as DEVICE_RESET_RECEIPT_SCHEMA
from .device_fresh_reset import build_reset_receipt
from .device_fresh_reset import execute_inventory as execute_device_reset_inventory
from .device_fresh_reset import freeze_inventory as freeze_device_reset_inventory
from .device_fresh_reset import verify_inventory as verify_device_reset_inventory
from .device_fresh_reset import verify_reset_receipt
from .composite_startup import CompositeSQLiteStartupProof
from .composite_startup import SQLiteStartupCompositionExpectation
from .composite_startup import SQLiteStartupCompositionProof
from .composite_startup import SQLiteStartupCompositionVerificationError
from .composite_startup import verify_composite_store_schema_read_only
from .extension_state import ExtensionStateStore
from .extension_state import ExtensionStateStoreError
from .extension_state import SQLiteExtensionStateProjectionQuery
from .external_qualification_ledger import ProtectedQualificationLedgerPort
from .external_qualification_ledger import SQLiteProtectedQualificationLedger
from .workspace_operation_ledger import SQLiteWorkspaceOperationLedger
from .workspace_operation_ledger import SQLiteWorkspaceOperationLedgerError
from .revision_path_queries import SQLiteRevisionPathVerificationQuery
from .entity_codecs import AgentAuthorityLeaseSQLiteKernelEntityCodec
from .entity_codecs import AgentMemberSQLiteKernelEntityCodec
from .entity_codecs import AgentRuntimeSignalSQLiteKernelEntityCodec
from .entity_codecs import ApprovalRequestSQLiteKernelEntityCodec
from .entity_codecs import ConversationMessageSQLiteKernelEntityCodec
from .entity_codecs import ContinuationSQLiteKernelEntityCodec
from .entity_codecs import ControlledOperationSQLiteKernelEntityCodec
from .entity_codecs import FailureObservationSQLiteKernelEntityCodec
from .entity_codecs import InboxMessageSQLiteKernelEntityCodec
from .entity_codecs import KernelCommandReceiptSQLiteKernelEntityCodec
from .entity_codecs import LaneSQLiteKernelEntityCodec
from .entity_codecs import MemorySQLiteKernelEntityCodec
from .entity_codecs import PublishedRevisionSQLiteKernelEntityCodec
from .entity_codecs import ProjectRepositoryBindingHeadSQLiteKernelEntityCodec
from .entity_codecs import ProjectRepositoryBindingSQLiteKernelEntityCodec
from .entity_codecs import ProtocolRecordSQLiteKernelEntityCodec
from .entity_codecs import RevisionPathVerificationSQLiteKernelEntityCodec
from .entity_codecs import RuntimeContinuationIntentSQLiteKernelEntityCodec
from .entity_codecs import RuntimeOutcomeConsumptionSQLiteKernelEntityCodec
from .entity_codecs import RuntimeSettlementIntentSQLiteKernelEntityCodec
from .entity_codecs import RuntimeTurnCommandSQLiteKernelEntityCodec
from .entity_codecs import SessionCapabilityBindingSQLiteKernelEntityCodec
from .entity_codecs import SessionCompositionPinSQLiteKernelEntityCodec
from .entity_codecs import SessionRepositoryBindingPinSQLiteKernelEntityCodec
from .entity_codecs import SessionRuntimeLeaseSQLiteKernelEntityCodec
from .entity_codecs import SessionSQLiteKernelEntityCodec
from .entity_codecs import TaskSQLiteKernelEntityCodec
from .entity_codecs import TaskEvidenceSQLiteKernelEntityCodec
from .entity_codecs import VerifiedWorkspaceCheckpointSQLiteKernelEntityCodec
from .entity_codecs import WorkspaceGenerationSQLiteKernelEntityCodec
from .entity_codecs import WorkspacePublicationIntentSQLiteKernelEntityCodec
from .entity_codecs import WorkspaceRuntimeBindingSQLiteKernelEntityCodec
from .entity_codecs import kernel_entity_codecs
from .migration_catalog import ClosedSQLiteMigrationCatalog
from .migration_catalog import SQLiteMigrationCatalogError
from .migration_catalog import SQLiteMigrationDescriptor
from .migration_catalog import STORE_MIGRATION_CATALOG
from .migration_catalog import STORE_MIGRATIONS
from .migration_catalog import STORE_SCHEMA_GENERATION
from .migration_catalog import STORE_SCHEMA_USER_VERSION
from .migration_catalog import install_store_schema_for_offline_migration
from .migration_catalog import schema_manifest_digest
from .migration_catalog import schema_object_rows
from .offline_cutover import OFFLINE_BACKUP_RECEIPT_SCHEMA_VERSION
from .offline_cutover import OFFLINE_CUTOVER_LEDGER_SCHEMA_VERSION
from .offline_cutover import SESSION_CUTOVER_DISPOSITION_SCHEMA_VERSION
from .offline_cutover import OfflineBackupKind
from .offline_cutover import OfflineBackupReceipt
from .offline_cutover import OfflineCutoverDisposition
from .offline_cutover import OfflineCutoverItem
from .offline_cutover import OfflineCutoverItemKind
from .offline_cutover import OfflineCutoverLedgerReceipt
from .offline_cutover import OfflineCutoverState
from .offline_cutover import SessionCutoverDisposition
from .offline_cutover import SessionCutoverDispositionKind
from .offline_cutover_apply import OfflineCutoverApplicationPlan
from .offline_cutover_apply import OfflineCutoverDeploymentProof
from .offline_cutover_apply import OfflineSessionAdoption
from .offline_cutover_apply import apply_offline_cutover_transaction
from .offline_cutover_apply import verify_offline_cutover_deployment_read_only
from .offline_cutover_planning import CutoverInventoryKind
from .offline_cutover_planning import CutoverInventoryObservation
from .offline_cutover_planning import CutoverRecoveryAction
from .offline_cutover_planning import LegacySessionCutoverObservation
from .offline_cutover_planning import OfflineBackupObservation
from .offline_cutover_planning import OfflineBackupSetProof
from .offline_cutover_planning import OfflineCutoverDryRunProof
from .offline_cutover_planning import OfflineQuiescenceReceipt
from .offline_cutover_planning import QuiescenceObservation
from .offline_cutover_planning import QuiescenceRequirement
from .offline_cutover_planning import QuiescenceSurfaceKind
from .offline_cutover_planning import RecoveryBoundary
from .offline_cutover_planning import build_offline_cutover_dry_run
from .offline_cutover_planning import classify_legacy_session
from .offline_cutover_planning import select_cutover_recovery_action
from .offline_cutover_planning import verify_offline_backup_set
from .offline_cutover_planning import verify_offline_quiescence
from .owner_startup import OWNER_SCHEMA_PROOF
from .owner_startup import ENZYMEDESIGN_OWNER_SCHEMA_PROFILE
from .owner_startup import OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE
from .owner_startup import OwnerPartitionedSchemaProof
from .owner_startup import OwnerPartitionedSchemaVerificationError
from .owner_startup import OwnerSchemaProfile
from .owner_startup import verify_owner_partitioned_schema_read_only
from .owner_startup import install_owner_partitioned_schema_for_offline_migration
from .legacy_deployment_schema_proofs import DeploymentSchemaProofError
from .legacy_deployment_schema_proofs import FRESH_INSTALL_MIGRATION_SOURCE
from .legacy_deployment_schema_proofs import FRESH_INSTALL_RECEIPT_SCHEMA
from .legacy_deployment_schema_proofs import FreshInstallBootstrapReceipt
from .legacy_deployment_schema_proofs import build_fresh_install_bootstrap_receipt
from .legacy_deployment_schema_proofs import canonical_digest
from .legacy_deployment_schema_proofs import verify_fresh_install_bootstrap
from .legacy_deployment_schema_proofs import verify_offline_removal_ledger
from .legacy_migration_assets import CURRENT_SQLITE_SCHEMA_VERSION
from .legacy_migration_assets import FINAL_SCHEMA_GENERATION
from .legacy_migration_assets import FINAL_SCHEMA_MANIFEST_DIGEST
from .legacy_migration_assets import FRESH_INSTALL_BOOTSTRAP_RECEIPT_DIGEST
from .legacy_migration_assets import MIGRATION_IDS
from .legacy_migration_assets import SQLiteSchemaMismatchError
from .legacy_migration_assets import _schema_manifest_digest
from .legacy_migration_assets import apply_sqlite_migrations
from .legacy_migration_assets import get_migration_sql
from .persistence import SQLiteCompositionIdentityRepository
from .persistence import SQLitePersistenceError
from .persistence import SQLiteResourceCapabilityFactRepository
from .persistence import SQLiteSessionCapabilityBindingRepository
from .startup import SQLiteStartupSchemaProof
from .startup import SQLiteStartupVerificationError
from .startup import STORE_OBJECT_OWNER
from .startup import verify_store_schema_read_only
from .startup_composition_state import SessionCompositionStateProof
from .startup_composition_state import verify_session_composition_state_read_only
from .unit_of_work import SQLiteExtensionTransactionCoordinator
from .unit_of_work import SQLiteUnitOfWork
from .unit_of_work import SQLiteUnitOfWorkError

COMPONENT_ID = "openzyme.store.sqlite"
COMPONENT_KIND = "adapter"
MIGRATION_STATE = "target_implemented_legacy_callers_pending"

__all__ = [
    "COMPONENT_ID",
    "COMPONENT_KIND",
    "MIGRATION_STATE",
    "SQLITE_STORE_ADAPTER_CONTRACT_DIGEST",
    "SQLITE_STORE_CONFIGURATION_SCHEMA_DIGEST",
    "SQLITE_STORE_PREFLIGHT_CONTRACT_DIGEST",
    "ClosedSQLiteMigrationCatalog",
    "CompositeSQLiteStartupProof",
    "CURRENT_SQLITE_SCHEMA_VERSION",
    "CutoverInventoryKind",
    "CutoverInventoryObservation",
    "CutoverRecoveryAction",
    "DEPLOYMENT_SCHEMA_STATE_SCHEMA_VERSION",
    "DeploymentProofVariant",
    "DeploymentSchemaProofError",
    "DeviceFreshResetError",
    "DEVICE_RESET_INVENTORY_SCHEMA",
    "DEVICE_RESET_RECEIPT_SCHEMA",
    "ENZYMEDESIGN_OWNER_SCHEMA_PROFILE",
    "ExtensionStateStore",
    "ExtensionStateStoreError",
    "SQLiteExtensionStateProjectionQuery",
    "ProtectedQualificationLedgerPort",
    "SQLiteProtectedQualificationLedger",
    "FINAL_SCHEMA_GENERATION",
    "FINAL_SCHEMA_MANIFEST_DIGEST",
    "FRESH_INSTALL_BOOTSTRAP_RECEIPT_DIGEST",
    "FRESH_INSTALL_BOOTSTRAP_RECEIPT_SCHEMA_VERSION",
    "FRESH_INSTALL_MIGRATION_SOURCE",
    "FRESH_INSTALL_RECEIPT_SCHEMA",
    "FreshInstallBootstrapReceipt",
    "FreshInstallBootstrapReceiptV2",
    "FreshInstallCompositionSeed",
    "FreshInstallDeploymentProof",
    "MIGRATION_IDS",
    "LegacySessionCutoverObservation",
    "MigrationSourceIdentity",
    "OFFLINE_BACKUP_RECEIPT_SCHEMA_VERSION",
    "OFFLINE_CUTOVER_LEDGER_SCHEMA_VERSION",
    "OfflineBackupKind",
    "OfflineBackupObservation",
    "OfflineBackupReceipt",
    "OfflineBackupSetProof",
    "OfflineCutoverApplicationPlan",
    "OfflineCutoverDeploymentProof",
    "OfflineCutoverDisposition",
    "OfflineCutoverDryRunProof",
    "OfflineCutoverItem",
    "OfflineCutoverItemKind",
    "OfflineCutoverLedgerReceipt",
    "OfflineCutoverState",
    "OfflineQuiescenceReceipt",
    "OfflineSessionAdoption",
    "OWNER_SCHEMA_PROOF",
    "OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE",
    "OwnerPartitionedSchemaProof",
    "OwnerPartitionedSchemaVerificationError",
    "OwnerSchemaProfile",
    "QuiescenceObservation",
    "QuiescenceRequirement",
    "QuiescenceSurfaceKind",
    "RecoveryBoundary",
    "SQLiteCompositionIdentityRepository",
    "SQLiteConnectionProvider",
    "SQLiteControlStore",
    "SQLiteControlStoreError",
    "SQLiteDeploymentProofError",
    "SQLiteExtensionTransactionCoordinator",
    "SQLiteMigrationCatalogError",
    "SQLiteMigrationDescriptor",
    "SQLiteKernelEntityCodec",
    "SQLiteKernelUnitOfWork",
    "SQLitePersistenceError",
    "SQLiteResourceCapabilityFactRepository",
    "SQLiteSessionCapabilityBindingRepository",
    "AgentAuthorityLeaseSQLiteKernelEntityCodec",
    "AgentMemberSQLiteKernelEntityCodec",
    "AgentRuntimeSignalSQLiteKernelEntityCodec",
    "ApprovalRequestSQLiteKernelEntityCodec",
    "ConversationMessageSQLiteKernelEntityCodec",
    "ContinuationSQLiteKernelEntityCodec",
    "ControlledOperationSQLiteKernelEntityCodec",
    "FailureObservationSQLiteKernelEntityCodec",
    "InboxMessageSQLiteKernelEntityCodec",
    "KernelCommandReceiptSQLiteKernelEntityCodec",
    "LaneSQLiteKernelEntityCodec",
    "MemorySQLiteKernelEntityCodec",
    "PublishedRevisionSQLiteKernelEntityCodec",
    "ProjectRepositoryBindingHeadSQLiteKernelEntityCodec",
    "ProjectRepositoryBindingSQLiteKernelEntityCodec",
    "ProtocolRecordSQLiteKernelEntityCodec",
    "RevisionPathVerificationSQLiteKernelEntityCodec",
    "RuntimeContinuationIntentSQLiteKernelEntityCodec",
    "RuntimeOutcomeConsumptionSQLiteKernelEntityCodec",
    "RuntimeSettlementIntentSQLiteKernelEntityCodec",
    "RuntimeTurnCommandSQLiteKernelEntityCodec",
    "SessionCapabilityBindingSQLiteKernelEntityCodec",
    "SessionCompositionPinSQLiteKernelEntityCodec",
    "SessionRepositoryBindingPinSQLiteKernelEntityCodec",
    "SessionRuntimeLeaseSQLiteKernelEntityCodec",
    "SessionSQLiteKernelEntityCodec",
    "TaskSQLiteKernelEntityCodec",
    "TaskEvidenceSQLiteKernelEntityCodec",
    "VerifiedWorkspaceCheckpointSQLiteKernelEntityCodec",
    "WorkspaceGenerationSQLiteKernelEntityCodec",
    "WorkspacePublicationIntentSQLiteKernelEntityCodec",
    "WorkspaceRuntimeBindingSQLiteKernelEntityCodec",
    "kernel_entity_codecs",
    "SQLiteSchemaMismatchError",
    "SQLiteStartupSchemaProof",
    "SQLiteStartupCompositionExpectation",
    "SQLiteStartupCompositionProof",
    "SQLiteStartupCompositionVerificationError",
    "SQLiteStartupVerificationError",
    "SQLiteStoreAdapterError",
    "SQLiteStoreConfiguration",
    "SQLiteStorePreflightObservation",
    "SQLiteUnitOfWork",
    "SQLiteUnitOfWorkError",
    "SQLiteWorkspaceOperationLedger",
    "SQLiteWorkspaceOperationLedgerError",
    "SQLiteRevisionPathVerificationQuery",
    "SESSION_CUTOVER_DISPOSITION_SCHEMA_VERSION",
    "SessionCutoverDisposition",
    "SessionCutoverDispositionKind",
    "SessionCompositionStateProof",
    "STORE_MIGRATION_CATALOG",
    "STORE_MIGRATIONS",
    "STORE_OBJECT_OWNER",
    "STORE_SCHEMA_GENERATION",
    "STORE_SCHEMA_USER_VERSION",
    "install_store_schema_for_offline_migration",
    "install_owner_partitioned_schema_for_offline_migration",
    "_schema_manifest_digest",
    "apply_sqlite_migrations",
    "apply_offline_cutover_transaction",
    "build_fresh_install_bootstrap_receipt",
    "build_reset_receipt",
    "execute_device_reset_inventory",
    "freeze_device_reset_inventory",
    "build_offline_cutover_dry_run",
    "canonical_digest",
    "classify_legacy_session",
    "select_cutover_recovery_action",
    "get_migration_sql",
    "schema_manifest_digest",
    "schema_object_rows",
    "seed_fresh_install_composition_offline",
    "verify_store_schema_read_only",
    "verify_composite_store_schema_read_only",
    "verify_fresh_install_bootstrap",
    "verify_fresh_install_deployment_read_only",
    "verify_device_reset_inventory",
    "verify_offline_backup_set",
    "verify_offline_cutover_deployment_read_only",
    "verify_offline_quiescence",
    "verify_offline_removal_ledger",
    "verify_reset_receipt",
    "verify_owner_partitioned_schema_read_only",
    "verify_session_composition_state_read_only",
    *_authority_mapping_exports,
]
