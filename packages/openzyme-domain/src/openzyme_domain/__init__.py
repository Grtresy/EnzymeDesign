from .models import ArtifactKind
from .models import RunStatus
from .models import SourceRefKind
from .models import utc_now_iso
from .failures import AGENT_TURN_BUDGET_EXHAUSTED_ERROR_CODE
from .failures import FAILURE_OBSERVATION_SCHEMA_VERSION
from .failures import FailureActorKind
from .failures import FailureClass
from .failures import FailureObservation
from .failures import FailureRecoverability
from .failures import likely_causes_for_error_code
from .file_workspace_public import FILE_WORKSPACE_PUBLIC_SCHEMA_VERSION
from .file_workspace_public import ExecutorOwnerWorkspaceView
from .file_workspace_public import FileWorkspacePublicProjection
from .historical_artifacts import HistoricalArtifactEligibility
from .historical_artifacts import HistoricalArtifactMigrationReceipt
from .historical_artifacts import HistoricalArtifactMigrationUnitReceipt
from .historical_artifacts import HistoricalArtifactRef
from .historical_artifacts import HistoricalArtifactStorage
from .historical_artifacts import canonical_historical_artifact_digest
from .scientific_attempts import (
    SCIENTIFIC_ARTIFACT_MATERIALIZATION_SCHEMA_VERSION,
)
from .scientific_attempts import (
    SCIENTIFIC_ATTEMPT_ADMISSION_REQUEST_SCHEMA_VERSION,
)
from .scientific_attempts import SCIENTIFIC_ATTEMPT_AUTHORIZATION_SCHEMA_VERSION
from .scientific_attempts import (
    SCIENTIFIC_ATTEMPT_CLOSURE_REQUEST_SCHEMA_VERSION,
)
from .scientific_attempts import SCIENTIFIC_ATTEMPT_CLOSURE_SCHEMA_VERSION
from .scientific_attempts import SCIENTIFIC_ATTEMPT_SCHEMA_VERSION
from .scientific_attempts import SCIENTIFIC_CHAIN_SELECTION_SCHEMA_VERSION
from .scientific_attempts import SCIENTIFIC_EFFECT_ADOPTION_SCHEMA_VERSION
from .scientific_attempts import SCIENTIFIC_OPERATION_DISPOSITION_SCHEMA_VERSION
from .scientific_attempts import ScientificArtifactMaterialization
from .scientific_attempts import ScientificAttempt
from .scientific_attempts import ScientificAttemptAdmissionRequest
from .scientific_attempts import ScientificAttemptAuthorization
from .scientific_attempts import ScientificAttemptAuthorityStatus
from .scientific_attempts import ScientificAttemptClosure
from .scientific_attempts import ScientificAttemptClosureRequest
from .scientific_attempts import ScientificAttemptLifecyclePhase
from .scientific_attempts import ScientificAttemptScope
from .scientific_attempts import ScientificAttemptStatus
from .scientific_attempts import ScientificChainSelection
from .scientific_attempts import ScientificEffectAdoption
from .scientific_attempts import ScientificOperationDisposition
from .scientific_attempts import ScientificOperationDispositionKind
from .scientific_attempts import ScientificSelectionState
from .scientific_deliverables import ScientificDeliverableBundle
from .scientific_deliverables import ScientificDeliverableRef
from .scientific_deliverables import ScientificDeliverableValidationReceipt
from .scientific_deliverables import ScientificFileStorage
from .scientific_deliverables import ScientificFileEffectAdoption
from .scientific_deliverables import canonical_scientific_deliverable_digest
from .scientific_deliverables import normalize_scientific_path
from .reliability import CONTROLLED_OPERATION_EXECUTION_EVENT_SCHEMA_VERSION
from .reliability import CONTROLLED_OPERATION_EXECUTION_SCHEMA_VERSION
from .reliability import CONTROLLED_OPERATION_DISPATCH_REQUEST_SCHEMA_VERSION
from .reliability import CONTROLLED_OPERATION_RESULT_HANDLE_SCHEMA_VERSION
from .reliability import CONTINUATION_STATE_SCHEMA_VERSION
from .reliability import MUTATION_SCOPE_SCHEMA_VERSION
from .reliability import MUTATION_WRITER_SCHEMA_VERSION
from .reliability import QUIESCENCE_RECEIPT_SCHEMA_VERSION
from .reliability import QUIESCENCE_SNAPSHOT_SCHEMA_VERSION
from .reliability import RUNTIME_COMMAND_SCHEMA_VERSION
from .reliability import ContinuationDeliveryState
from .reliability import ContinuationResumeStrategy
from .reliability import ControlledOperationExecution
from .reliability import ControlledOperationExecutionEvent
from .reliability import ControlledOperationDispatchRequest
from .reliability import ControlledOperationProviderDispatchReceipt
from .reliability import ControlledOperationProviderObservationReceipt
from .reliability import ControlledOperationExecutionLifecycle
from .reliability import ControlledOperationExecutionPhase
from .reliability import ControlledOperationExecutionTerminalOutcome
from .reliability import ControlledOperationOwnerMode
from .reliability import ControlledOperationResultHandle
from .reliability import ExternalEffectCertainty
from .reliability import MutationScope
from .reliability import MutationScopeKind
from .reliability import MutationScopeState
from .reliability import MutationWriter
from .reliability import MutationWriterKind
from .reliability import MutationWriterState
from .reliability import QuiescenceReceipt
from .reliability import QuiescenceSnapshot
from .reliability import RetryEligibility
from .reliability import RuntimeCommandRecord
from .reliability import RuntimeCommandStatus
from .reliability import RuntimeCommandType
from .control_plane import CONTROL_PLANE_ENTITY_NAMES
from .control_plane import AgentMember
from .control_plane import AgentMemberStatus
from .control_plane import AgentRuntimeSignal
from .control_plane import AgentRuntimeSignalReason
from .control_plane import AgentRuntimeSignalStatus
from .control_plane import SessionRuntimeLease
from .control_plane import SessionRuntimeLeaseMode
from .control_plane import ApprovalRequest
from .control_plane import ApprovalRequestStatus
from .control_plane import CommandLogArtifactRecord
from .control_plane import ControlledOperation
from .control_plane import ControlledOperationStatus
from .control_plane import ContinuationState
from .control_plane import ContinuationStateStatus
from .control_plane import EngineInvocation
from .control_plane import EngineInvocationStatus
from .control_plane import FileAuditEntry
from .control_plane import InboxMessage
from .control_plane import InboxParticipantKind
from .control_plane import InboxStatus
from .control_plane import Lane
from .control_plane import LaneStatus
from .control_plane import MemoryEntry
from .control_plane import MemoryKind
from .control_plane import MemoryScopeKind
from .control_plane import RunRecord
from .control_plane import SandboxImageCompatibility
from .control_plane import SandboxImageRecord
from .control_plane import SandboxRunRecord
from .control_plane import SandboxRunStatus
from .control_plane import SandboxWorkspaceRecord
from .control_plane import SandboxWorkspaceStatus
from .control_plane import ResearchEvidence
from .control_plane import ResearchGap
from .control_plane import ResearchSourceRef
from .control_plane import ResearchSummary
from .control_plane import ResearchSummaryStatus
from .control_plane import SessionReportDraftRecord
from .control_plane import SessionReportDraftStatus
from .control_plane import SessionReportRecord
from .control_plane import SessionReportStatus
from .control_plane import SessionArtifactRecord
from .control_plane import Session
from .control_plane import SessionStatus
from .control_plane import Task
from .control_plane import TaskPriority
from .control_plane import TaskStatus
from .repository_bindings import GitObjectFormat
from .repository_bindings import PROJECT_REPOSITORY_BINDING_SCHEMA_VERSION
from .repository_bindings import ProjectRepositoryBinding
from .repository_bindings import RepositoryBindingDriftKind
from .repository_bindings import RepositoryBindingLifecycleStatus
from .repository_bindings import RepositoryRefClass
from .repository_bindings import RepositoryRefNamespacePolicy
from .repository_bindings import SESSION_REPOSITORY_BINDING_PIN_SCHEMA_VERSION
from .repository_bindings import SessionRepositoryBindingPin
from .repository_bindings import SessionRepositoryBindingStatus
from .git_lfs_work_products import GIT_LFS_BINDING_POLICY_SCHEMA_VERSION
from .git_lfs_work_products import GIT_LFS_CLOSURE_MANIFEST_SCHEMA_VERSION
from .git_lfs_work_products import GIT_LFS_GC_CANDIDATE_RECEIPT_SCHEMA_VERSION
from .git_lfs_work_products import GIT_LFS_OBJECT_READ_RECEIPT_SCHEMA_VERSION
from .git_lfs_work_products import GIT_LFS_POINTER_VERSION
from .git_lfs_work_products import GIT_LFS_UPLOAD_SESSION_SCHEMA_VERSION
from .git_lfs_work_products import GitLfsBindingPolicy
from .git_lfs_work_products import GitLfsClosureEntry
from .git_lfs_work_products import GitLfsClosureManifest
from .git_lfs_work_products import GitLfsClosureVerification
from .git_lfs_work_products import GitLfsGcCandidateReceipt
from .git_lfs_work_products import GitLfsObjectReadReceipt
from .git_lfs_work_products import GitLfsPathRepresentation
from .git_lfs_work_products import GitLfsPathRule
from .git_lfs_work_products import GitLfsPointer
from .git_lfs_work_products import GitLfsPrivateReachabilityReceipt
from .git_lfs_work_products import GitLfsRetentionClass
from .git_lfs_work_products import GitLfsUploadSession
from .git_lfs_work_products import GitLfsUploadStatus
from .git_lfs_work_products import canonical_lfs_digest
from .git_lfs_work_products import require_repository_path
from .revision_path_handoffs import CONTROLLED_OPERATION_RESULT_REF_SCHEMA_VERSION
from .revision_path_handoffs import PROTOCOL_FILE_HANDOFF_SCHEMA_VERSION
from .revision_path_handoffs import REPORT_REF_SCHEMA_VERSION
from .revision_path_handoffs import REVISION_PATH_REF_SCHEMA_VERSION
from .revision_path_handoffs import SCIENTIFIC_DELIVERABLE_REF_SCHEMA_VERSION
from .revision_path_handoffs import TASK_EVIDENCE_REF_SCHEMA_VERSION
from .revision_path_handoffs import ControlledOperationResultRef
from .revision_path_handoffs import ProtocolFileHandoff
from .revision_path_handoffs import ReportRef
from .revision_path_handoffs import RevisionPathEntryKind
from .revision_path_handoffs import RevisionPathRef
from .revision_path_handoffs import TaskEvidenceKind
from .revision_path_handoffs import TaskEvidenceRef
from .revision_path_handoffs import canonical_handoff_digest
from .executor_hpc_workspaces import EXECUTOR_HPC_CLEANUP_INTENT_SCHEMA_VERSION
from .executor_hpc_workspaces import EXECUTOR_HPC_CLEANUP_RECEIPT_SCHEMA_VERSION
from .executor_hpc_workspaces import EXECUTOR_HPC_CREDENTIAL_CLAIM_SCHEMA_VERSION
from .executor_hpc_workspaces import EXECUTOR_HPC_PROVISION_INTENT_SCHEMA_VERSION
from .executor_hpc_workspaces import EXECUTOR_HPC_PROVISION_RECEIPT_SCHEMA_VERSION
from .executor_hpc_workspaces import EXECUTOR_HPC_TARGET_QUALIFICATION_SCHEMA_VERSION
from .executor_hpc_workspaces import EXECUTOR_HPC_WORKSPACE_SCHEMA_VERSION
from .executor_hpc_workspaces import ExecutorHpcCredentialClaim
from .executor_hpc_workspaces import ExecutorHpcCredentialOperation
from .executor_hpc_workspaces import ExecutorHpcCleanupDisposition
from .executor_hpc_workspaces import ExecutorHpcTargetQualification
from .executor_hpc_workspaces import ExecutorHpcWorkspace
from .executor_hpc_workspaces import ExecutorHpcWorkspaceCleanupIntent
from .executor_hpc_workspaces import ExecutorHpcWorkspaceCleanupReceipt
from .executor_hpc_workspaces import ExecutorHpcWorkspaceProvisionIntent
from .executor_hpc_workspaces import ExecutorHpcWorkspaceProvisionReceipt
from .executor_hpc_workspaces import ExecutorHpcWorkspaceState
from .executor_hpc_workspaces import canonical_executor_hpc_digest
from .workspace_revision_executions import ComputeSourceManifest
from .workspace_revision_executions import ComputeSourceManifestEntry
from .workspace_revision_executions import ExternalJobHandle
from .workspace_revision_executions import ExternalJobObservation
from .workspace_revision_executions import SchedulerCredentialOccurrence
from .workspace_revision_executions import SchedulerCredentialOccurrenceState
from .workspace_revision_executions import WorkspaceExternalBackend
from .workspace_revision_executions import WorkspaceJobCancellationIntent
from .workspace_revision_executions import WorkspaceJobCancellationReceipt
from .workspace_revision_executions import WorkspaceJobDispatchIntent
from .workspace_revision_executions import WorkspaceJobExecutionMode
from .workspace_revision_executions import WorkspaceJobObservationState
from .workspace_revision_executions import WorkspaceJobResult
from .workspace_revision_executions import WorkspaceJobResultRevisionLink
from .workspace_revision_executions import WorkspaceJobTargetQualification
from .workspace_revision_executions import WorkspaceRevisionCleanObservation
from .workspace_revision_executions import WorkspaceRevisionExecutionRequest
from .workspace_revision_executions import WorkspaceRevisionScientificBasis
from .workspace_revision_executions import WorkspaceRevisionSourceClass
from .workspace_revision_executions import canonical_workspace_job_digest
from .agent_capability_leases import AGENT_CAPABILITY_LEASE_EVENT_SCHEMA_VERSION
from .agent_capability_leases import AGENT_CAPABILITY_LEASE_SCHEMA_VERSION
from .agent_capability_leases import (
    AGENT_RETIREMENT_CLEANUP_PROOF_SCHEMA_VERSION,
)
from .agent_capability_leases import AGENT_RETIREMENT_RECORD_SCHEMA_VERSION
from .agent_capability_leases import AGENT_RETIREMENT_REQUEST_SCHEMA_VERSION
from .agent_capability_leases import (
    AGENT_WORKSPACE_GENERATION_RESERVATION_SCHEMA_VERSION,
)
from .agent_capability_leases import EXECUTOR_AGENT_CAPABILITIES
from .agent_capability_leases import GENERAL_AGENT_CAPABILITIES
from .agent_capability_leases import AgentCapability
from .agent_capability_leases import AgentCapabilityLease
from .agent_capability_leases import AgentCapabilityLeaseEventKind
from .agent_capability_leases import AgentCapabilityLeaseLifecycleEvent
from .agent_capability_leases import AgentCapabilityLeaseStatus
from .agent_capability_leases import AgentCapabilityProfile
from .agent_capability_leases import AgentCapabilityRevocationReason
from .agent_capability_leases import AgentCapabilityRevocationScope
from .agent_capability_leases import AgentRetirementReason
from .agent_capability_leases import AgentRetirementCleanupProofRecord
from .agent_capability_leases import AgentRetirementRecord
from .agent_capability_leases import AgentRetirementRequest
from .agent_capability_leases import AgentWorkspaceGenerationReservation
from .agent_capability_leases import AgentWorkspaceGenerationStatus
from .agent_capability_leases import AgentWorkspaceReadinessOwnerKind
from .agent_capability_leases import canonical_capability_digest
from .agent_capability_leases import capabilities_for_profile
from .agent_capability_leases import capability_set_digest
from .agent_capability_leases import target_scope_digest
from .agent_git_workspaces import AGENT_GIT_WORKSPACE_OBSERVATION_SCHEMA_VERSION
from .agent_git_workspaces import (
    AGENT_GIT_WORKSPACE_RESTORE_COMPARISON_SCHEMA_VERSION,
)
from .agent_git_workspaces import AGENT_GIT_WORKSPACE_SCHEMA_VERSION
from .agent_git_workspaces import AgentGitDirectoryKind
from .agent_git_workspaces import AgentGitWorkspace
from .agent_git_workspaces import AgentGitWorkspaceBlockerCode
from .agent_git_workspaces import AgentGitWorkspaceIdentityDriftKind
from .agent_git_workspaces import AgentGitWorkspaceObservation
from .agent_git_workspaces import AgentGitWorkspaceRestoreComparison
from .agent_git_workspaces import AgentGitWorkspaceStatus
from .agent_git_workspaces import canonical_workspace_digest
from .agent_git_workspaces import compare_agent_git_workspace_identity
from .workspace_checkpoints import PrivateRefAdvanceKind
from .workspace_checkpoints import AGENT_WORKSPACE_STATE_OBSERVATION_SCHEMA_VERSION
from .workspace_checkpoints import AgentWorkspaceStateObservation
from .workspace_checkpoints import CLEAN_COMMITTED_REVISION_PROOF_SCHEMA_VERSION
from .workspace_checkpoints import CleanCommittedRevisionProof
from .workspace_checkpoints import REMOTE_PRIVATE_REF_OBSERVATION_SCHEMA_VERSION
from .workspace_checkpoints import RemotePrivateRefObservation
from .workspace_checkpoints import WORKSPACE_CHECKPOINT_PROOF_INPUT_SCHEMA_VERSION
from .workspace_checkpoints import WorkspaceCheckpointProofInput
from .workspace_checkpoints import VERIFIED_WORKSPACE_CHECKPOINT_SCHEMA_VERSION
from .workspace_checkpoints import VerifiedWorkspaceCheckpoint
from .workspace_checkpoints import WorkspaceDirtyState
from .workspace_checkpoints import WorkspaceFormalBoundary
from .workspace_publications import PUBLISHED_REVISION_SCHEMA_VERSION
from .workspace_publications import PUBLICATION_FETCH_IDENTITY_SCHEMA_VERSION
from .workspace_publications import WORKSPACE_PUBLICATION_INTENT_SCHEMA_VERSION
from .workspace_publications import WORKSPACE_PUBLICATION_MANIFEST_SCHEMA_VERSION
from .workspace_publications import (
    WORKSPACE_PUBLICATION_REMOTE_RECEIPT_SCHEMA_VERSION,
)
from .workspace_publications import PublicationFetchIdentity
from .workspace_publications import PublicationManifestEntry
from .workspace_publications import PublicationManifestObjectKind
from .workspace_publications import PublishedRevision
from .workspace_publications import WorkspacePublicationIntent
from .workspace_publications import WorkspacePublicationIntentState
from .workspace_publications import WorkspacePublicationManifest
from .workspace_publications import WorkspacePublicationRemoteReceipt
from .workspace_publications import WorkspacePublicationResult
from .workspace_publications import canonical_publication_digest

__all__ = [
    "AGENT_WORKSPACE_STATE_OBSERVATION_SCHEMA_VERSION",
    "AgentWorkspaceStateObservation",
    "CLEAN_COMMITTED_REVISION_PROOF_SCHEMA_VERSION",
    "CleanCommittedRevisionProof",
    "PrivateRefAdvanceKind",
    "REMOTE_PRIVATE_REF_OBSERVATION_SCHEMA_VERSION",
    "RemotePrivateRefObservation",
    "WORKSPACE_CHECKPOINT_PROOF_INPUT_SCHEMA_VERSION",
    "WorkspaceCheckpointProofInput",
    "VERIFIED_WORKSPACE_CHECKPOINT_SCHEMA_VERSION",
    "VerifiedWorkspaceCheckpoint",
    "WorkspaceDirtyState",
    "WorkspaceFormalBoundary",
    "AGENT_TURN_BUDGET_EXHAUSTED_ERROR_CODE",
    "AGENT_CAPABILITY_LEASE_EVENT_SCHEMA_VERSION",
    "AGENT_CAPABILITY_LEASE_SCHEMA_VERSION",
    "AGENT_RETIREMENT_CLEANUP_PROOF_SCHEMA_VERSION",
    "AGENT_RETIREMENT_RECORD_SCHEMA_VERSION",
    "AGENT_RETIREMENT_REQUEST_SCHEMA_VERSION",
    "AGENT_WORKSPACE_GENERATION_RESERVATION_SCHEMA_VERSION",
    "AGENT_GIT_WORKSPACE_OBSERVATION_SCHEMA_VERSION",
    "AGENT_GIT_WORKSPACE_RESTORE_COMPARISON_SCHEMA_VERSION",
    "AGENT_GIT_WORKSPACE_SCHEMA_VERSION",
    "AgentCapability",
    "AgentCapabilityLease",
    "AgentCapabilityLeaseEventKind",
    "AgentCapabilityLeaseLifecycleEvent",
    "AgentCapabilityLeaseStatus",
    "AgentCapabilityProfile",
    "AgentCapabilityRevocationReason",
    "AgentCapabilityRevocationScope",
    "AgentMember",
    "AgentMemberStatus",
    "AgentRetirementCleanupProofRecord",
    "AgentRetirementReason",
    "AgentRetirementRecord",
    "AgentRetirementRequest",
    "AgentRuntimeSignal",
    "AgentRuntimeSignalReason",
    "AgentRuntimeSignalStatus",
    "AgentWorkspaceGenerationReservation",
    "AgentWorkspaceGenerationStatus",
    "AgentWorkspaceReadinessOwnerKind",
    "AgentGitDirectoryKind",
    "AgentGitWorkspace",
    "AgentGitWorkspaceBlockerCode",
    "AgentGitWorkspaceIdentityDriftKind",
    "AgentGitWorkspaceObservation",
    "AgentGitWorkspaceRestoreComparison",
    "AgentGitWorkspaceStatus",
    "PUBLISHED_REVISION_SCHEMA_VERSION",
    "PUBLICATION_FETCH_IDENTITY_SCHEMA_VERSION",
    "WORKSPACE_PUBLICATION_INTENT_SCHEMA_VERSION",
    "WORKSPACE_PUBLICATION_MANIFEST_SCHEMA_VERSION",
    "WORKSPACE_PUBLICATION_REMOTE_RECEIPT_SCHEMA_VERSION",
    "PublicationFetchIdentity",
    "PublicationManifestEntry",
    "PublicationManifestObjectKind",
    "PublishedRevision",
    "WorkspacePublicationIntent",
    "WorkspacePublicationIntentState",
    "WorkspacePublicationManifest",
    "WorkspacePublicationRemoteReceipt",
    "WorkspacePublicationResult",
    "canonical_publication_digest",
    "SessionRuntimeLease",
    "SessionRuntimeLeaseMode",
    "ApprovalRequest",
    "ApprovalRequestStatus",
    "CommandLogArtifactRecord",
    "CONTROLLED_OPERATION_EXECUTION_EVENT_SCHEMA_VERSION",
    "CONTROLLED_OPERATION_EXECUTION_SCHEMA_VERSION",
    "CONTROLLED_OPERATION_DISPATCH_REQUEST_SCHEMA_VERSION",
    "CONTROLLED_OPERATION_RESULT_HANDLE_SCHEMA_VERSION",
    "CONTINUATION_STATE_SCHEMA_VERSION",
    "ControlledOperation",
    "ControlledOperationExecution",
    "ControlledOperationExecutionEvent",
    "ControlledOperationDispatchRequest",
    "ControlledOperationProviderDispatchReceipt",
    "ControlledOperationProviderObservationReceipt",
    "ControlledOperationExecutionLifecycle",
    "ControlledOperationExecutionPhase",
    "ControlledOperationExecutionTerminalOutcome",
    "ControlledOperationOwnerMode",
    "ControlledOperationResultHandle",
    "ControlledOperationStatus",
    "ContinuationDeliveryState",
    "ContinuationResumeStrategy",
    "ContinuationState",
    "ContinuationStateStatus",
    "CONTROL_PLANE_ENTITY_NAMES",
    "EngineInvocation",
    "EngineInvocationStatus",
    "EXECUTOR_AGENT_CAPABILITIES",
    "FAILURE_OBSERVATION_SCHEMA_VERSION",
    "FailureActorKind",
    "FailureClass",
    "FailureObservation",
    "FailureRecoverability",
    "FILE_WORKSPACE_PUBLIC_SCHEMA_VERSION",
    "ExecutorOwnerWorkspaceView",
    "FileWorkspacePublicProjection",
    "HistoricalArtifactEligibility",
    "HistoricalArtifactMigrationReceipt",
    "HistoricalArtifactMigrationUnitReceipt",
    "HistoricalArtifactRef",
    "HistoricalArtifactStorage",
    "GIT_LFS_BINDING_POLICY_SCHEMA_VERSION",
    "GIT_LFS_CLOSURE_MANIFEST_SCHEMA_VERSION",
    "GIT_LFS_GC_CANDIDATE_RECEIPT_SCHEMA_VERSION",
    "GIT_LFS_OBJECT_READ_RECEIPT_SCHEMA_VERSION",
    "GIT_LFS_POINTER_VERSION",
    "GIT_LFS_UPLOAD_SESSION_SCHEMA_VERSION",
    "GitLfsBindingPolicy",
    "GitLfsClosureEntry",
    "GitLfsClosureManifest",
    "GitLfsClosureVerification",
    "GitLfsGcCandidateReceipt",
    "GitLfsObjectReadReceipt",
    "GitLfsPathRepresentation",
    "GitLfsPathRule",
    "GitLfsPointer",
    "GitLfsPrivateReachabilityReceipt",
    "GitLfsRetentionClass",
    "GitLfsUploadSession",
    "GitLfsUploadStatus",
    "GitObjectFormat",
    "GENERAL_AGENT_CAPABILITIES",
    "SCIENTIFIC_ARTIFACT_MATERIALIZATION_SCHEMA_VERSION",
    "SCIENTIFIC_ATTEMPT_ADMISSION_REQUEST_SCHEMA_VERSION",
    "SCIENTIFIC_ATTEMPT_AUTHORIZATION_SCHEMA_VERSION",
    "SCIENTIFIC_ATTEMPT_CLOSURE_REQUEST_SCHEMA_VERSION",
    "SCIENTIFIC_ATTEMPT_CLOSURE_SCHEMA_VERSION",
    "SCIENTIFIC_ATTEMPT_SCHEMA_VERSION",
    "SCIENTIFIC_CHAIN_SELECTION_SCHEMA_VERSION",
    "SCIENTIFIC_EFFECT_ADOPTION_SCHEMA_VERSION",
    "SCIENTIFIC_OPERATION_DISPOSITION_SCHEMA_VERSION",
    "ScientificArtifactMaterialization",
    "ScientificAttempt",
    "ScientificAttemptAdmissionRequest",
    "ScientificAttemptAuthorization",
    "ScientificAttemptAuthorityStatus",
    "ScientificAttemptClosure",
    "ScientificAttemptClosureRequest",
    "ScientificAttemptLifecyclePhase",
    "ScientificAttemptScope",
    "ScientificAttemptStatus",
    "ScientificChainSelection",
    "ScientificEffectAdoption",
    "ScientificOperationDisposition",
    "ScientificOperationDispositionKind",
    "ScientificSelectionState",
    "ScientificDeliverableBundle",
    "ScientificDeliverableRef",
    "ScientificDeliverableValidationReceipt",
    "ScientificFileStorage",
    "ScientificFileEffectAdoption",
    "canonical_scientific_deliverable_digest",
    "normalize_scientific_path",
    "FileAuditEntry",
    "InboxMessage",
    "InboxParticipantKind",
    "InboxStatus",
    "Lane",
    "LaneStatus",
    "MemoryEntry",
    "MemoryKind",
    "MemoryScopeKind",
    "MUTATION_SCOPE_SCHEMA_VERSION",
    "MUTATION_WRITER_SCHEMA_VERSION",
    "MutationScope",
    "MutationScopeKind",
    "MutationScopeState",
    "MutationWriter",
    "MutationWriterKind",
    "MutationWriterState",
    "PROJECT_REPOSITORY_BINDING_SCHEMA_VERSION",
    "ProjectRepositoryBinding",
    "ExternalEffectCertainty",
    "QUIESCENCE_RECEIPT_SCHEMA_VERSION",
    "QUIESCENCE_SNAPSHOT_SCHEMA_VERSION",
    "QuiescenceReceipt",
    "QuiescenceSnapshot",
    "RetryEligibility",
    "RunRecord",
    "SandboxImageCompatibility",
    "SandboxImageRecord",
    "SandboxRunRecord",
    "SandboxRunStatus",
    "SandboxWorkspaceRecord",
    "SandboxWorkspaceStatus",
    "ResearchEvidence",
    "ResearchGap",
    "ResearchSourceRef",
    "ResearchSummary",
    "ResearchSummaryStatus",
    "RepositoryBindingDriftKind",
    "RepositoryBindingLifecycleStatus",
    "RepositoryRefClass",
    "RepositoryRefNamespacePolicy",
    "CONTROLLED_OPERATION_RESULT_REF_SCHEMA_VERSION",
    "PROTOCOL_FILE_HANDOFF_SCHEMA_VERSION",
    "REPORT_REF_SCHEMA_VERSION",
    "REVISION_PATH_REF_SCHEMA_VERSION",
    "SCIENTIFIC_DELIVERABLE_REF_SCHEMA_VERSION",
    "TASK_EVIDENCE_REF_SCHEMA_VERSION",
    "ControlledOperationResultRef",
    "ProtocolFileHandoff",
    "ReportRef",
    "RevisionPathEntryKind",
    "RevisionPathRef",
    "TaskEvidenceKind",
    "TaskEvidenceRef",
    "EXECUTOR_HPC_CLEANUP_INTENT_SCHEMA_VERSION",
    "EXECUTOR_HPC_CLEANUP_RECEIPT_SCHEMA_VERSION",
    "EXECUTOR_HPC_CREDENTIAL_CLAIM_SCHEMA_VERSION",
    "EXECUTOR_HPC_PROVISION_INTENT_SCHEMA_VERSION",
    "EXECUTOR_HPC_PROVISION_RECEIPT_SCHEMA_VERSION",
    "EXECUTOR_HPC_TARGET_QUALIFICATION_SCHEMA_VERSION",
    "EXECUTOR_HPC_WORKSPACE_SCHEMA_VERSION",
    "ExecutorHpcCredentialClaim",
    "ExecutorHpcCredentialOperation",
    "ExecutorHpcCleanupDisposition",
    "ExecutorHpcTargetQualification",
    "ExecutorHpcWorkspace",
    "ExecutorHpcWorkspaceCleanupIntent",
    "ExecutorHpcWorkspaceCleanupReceipt",
    "ExecutorHpcWorkspaceProvisionIntent",
    "ExecutorHpcWorkspaceProvisionReceipt",
    "ExecutorHpcWorkspaceState",
    "ComputeSourceManifest",
    "ComputeSourceManifestEntry",
    "ExternalJobHandle",
    "ExternalJobObservation",
    "SchedulerCredentialOccurrence",
    "SchedulerCredentialOccurrenceState",
    "WorkspaceExternalBackend",
    "WorkspaceJobCancellationIntent",
    "WorkspaceJobCancellationReceipt",
    "WorkspaceJobDispatchIntent",
    "WorkspaceJobExecutionMode",
    "WorkspaceJobObservationState",
    "WorkspaceJobResult",
    "WorkspaceJobResultRevisionLink",
    "WorkspaceJobTargetQualification",
    "WorkspaceRevisionCleanObservation",
    "WorkspaceRevisionExecutionRequest",
    "WorkspaceRevisionScientificBasis",
    "WorkspaceRevisionSourceClass",
    "SessionReportDraftRecord",
    "SessionReportDraftStatus",
    "SessionReportRecord",
    "SessionReportStatus",
    "SESSION_REPOSITORY_BINDING_PIN_SCHEMA_VERSION",
    "SessionRepositoryBindingPin",
    "SessionRepositoryBindingStatus",
    "ArtifactKind",
    "RunStatus",
    "RUNTIME_COMMAND_SCHEMA_VERSION",
    "RuntimeCommandRecord",
    "RuntimeCommandStatus",
    "RuntimeCommandType",
    "SessionArtifactRecord",
    "Session",
    "SessionStatus",
    "SourceRefKind",
    "Task",
    "TaskPriority",
    "TaskStatus",
    "utc_now_iso",
    "canonical_capability_digest",
    "canonical_lfs_digest",
    "canonical_handoff_digest",
    "canonical_historical_artifact_digest",
    "canonical_executor_hpc_digest",
    "canonical_workspace_job_digest",
    "capabilities_for_profile",
    "capability_set_digest",
    "canonical_workspace_digest",
    "compare_agent_git_workspace_identity",
    "likely_causes_for_error_code",
    "require_repository_path",
    "target_scope_digest",
]
