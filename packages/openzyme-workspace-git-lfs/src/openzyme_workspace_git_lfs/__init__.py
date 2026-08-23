"""Git/LFS workspace Adapter contracts and migration identity.

Installing this wheel does not activate a workspace backend; activation remains
manifest-driven and requires explicit repository locations.
"""

from .manifest_locator import GIT_LFS_COMPONENT_MANIFEST_DIGEST
from .qualification import GIT_LFS_QUALIFICATION_OPERATIONS
from .qualification import GitLfsQualificationOperationPort
from .qualification import GitLfsQualificationProbeBridge
from .qualification import LocalGitLfsPreparationCommandPort
from .qualification import LocalIsolatedGitLfsPreparationExecutor
from .qualification import SubprocessLocalGitLfsPreparationCommandPort

from .agent_workspaces import AGENT_GIT_WORKSPACE_OBSERVATION_SCHEMA_VERSION
from .agent_workspaces import AGENT_GIT_WORKSPACE_RESTORE_COMPARISON_SCHEMA_VERSION
from .agent_workspaces import AGENT_GIT_WORKSPACE_SCHEMA_VERSION
from .agent_workspaces import AgentGitDirectoryKind
from .agent_workspaces import AgentGitWorkspace
from .agent_workspaces import AgentGitWorkspaceBlockerCode
from .agent_workspaces import AgentGitWorkspaceIdentityDriftKind
from .agent_workspaces import AgentGitWorkspaceObservation
from .agent_workspaces import AgentGitWorkspaceRestoreComparison
from .agent_workspaces import AgentGitWorkspaceStatus
from .agent_workspaces import canonical_workspace_digest
from .agent_workspaces import compare_agent_git_workspace_identity
from .agent_git_workspace_repositories import AgentGitWorkspaceRepository
from .agent_git_workspace_repositories import AgentGitWorkspaceRepositoryError
from .agent_git_workspace_repositories import AgentGitWorkspaceVersionConflictError
from .compute_tree import GITLESS_COMPUTE_TREE_RECEIPT_SCHEMA_VERSION
from .compute_tree import GitlessComputeTreeReceipt
from .compute_tree import GitlessComputeTreeRequest
from .compute_tree import LocalGitlessComputeTreePreparer
from .credential_material import HmacRepositoryCredentialMaterialAdapter
from .credential_material import RepositoryCredentialMaterialError
from .credential_claims import IssuedRepositoryCredential
from .credential_claims import REPOSITORY_CREDENTIAL_SCHEMA_VERSION
from .credential_claims import RepositoryCredentialClaims
from .credential_claims import RepositoryCredentialError
from .credential_claims import RepositoryCredentialExpiredError
from .credential_claims import RepositoryCredentialRejectedError
from .credential_issuance import RepositoryCredentialIssueRequest
from .credential_issuance import RepositoryCredentialIssuanceStore
from .http_transport import AuthenticatedRepositoryRequest
from .http_transport import LFS_JSON_MEDIA_TYPE
from .http_transport import LfsBatchRequest
from .http_transport import LfsObjectRequest
from .http_transport import LfsVerifyRequest
from .http_transport import RepositoryServicePreflightError
from .http_transport import RepositoryTransportDependencies
from .http_transport import RepositoryTransportError
from .http_transport import RepositoryTransportRequestError
from .http_transport import create_repository_transport_app
from .clone import AgentGitWorkspaceProvisioningError
from .clone import AgentWorkspaceCloneResult
from .clone import AgentWorkspaceCloneRunner
from .clone import CloneCommandExecutor
from .clone import CloneCommandResult
from .clone import PodmanAgentWorkspaceCloneRunner
from .client_qualification import GIT_LFS_CLIENT_QUALIFICATION_SCHEMA_VERSION
from .client_qualification import GITLESS_COMPUTE_QUALIFICATION_SCHEMA_VERSION
from .client_qualification import GitLfsClientEnvironment
from .client_qualification import GitLfsClientQualification
from .client_qualification import GitLfsClientQualificationError
from .client_qualification import GitLfsNativeClientProbe
from .client_qualification import GitlessComputeQualification
from .client_qualification import qualify_gitless_compute
from .client_qualification import qualify_native_git_lfs_client
from .binding_mechanism import GitLfsRepositoryBindingMechanism
from .binding_mechanism import RepositoryEndpointSettings
from .lfs import GIT_LFS_BINDING_POLICY_SCHEMA_VERSION
from .lfs import GIT_LFS_CLOSURE_MANIFEST_SCHEMA_VERSION
from .lfs import GIT_LFS_CLOSURE_VERIFICATION_SCHEMA_VERSION
from .lfs import GIT_LFS_GC_CANDIDATE_RECEIPT_SCHEMA_VERSION
from .lfs import GIT_LFS_OBJECT_READ_RECEIPT_SCHEMA_VERSION
from .lfs import GIT_LFS_POINTER_VERSION
from .lfs import GIT_LFS_PRIVATE_REACHABILITY_RECEIPT_SCHEMA_VERSION
from .lfs import GIT_LFS_UPLOAD_SESSION_SCHEMA_VERSION
from .lfs import GitLfsBindingPolicy
from .lfs import GitLfsClosureEntry
from .lfs import GitLfsClosureManifest
from .lfs import GitLfsClosureVerification
from .lfs import GitLfsGcCandidateReceipt
from .lfs import GitLfsObjectReadReceipt
from .lfs import GitLfsPathRepresentation
from .lfs import GitLfsPathRule
from .lfs import GitLfsPointer
from .lfs import GitLfsPrivateReachabilityReceipt
from .lfs import GitLfsRetentionClass
from .lfs import GitLfsUploadSession
from .lfs import GitLfsUploadStatus
from .lfs import canonical_lfs_digest
from .lfs import require_repository_path
from .revision_backend import GitRepositoryLocation
from .revision_backend import GitRepositoryLocator
from .revision_backend import GitRevisionBackendError
from .revision_backend import LocalGitRevisionBackend
from .observation import AgentGitWorkspaceBaseCommitDriftError
from .observation import AgentGitWorkspaceCorruptionError
from .observation import AgentGitWorkspaceInfrastructureError
from .observation import AgentGitWorkspaceInvariantError
from .observation import AgentGitWorkspaceObservationProvider
from .observation import AgentGitWorkspacePermissionError
from .observation import AgentGitWorkspaceRecoveryError
from .observation import PodmanAgentGitWorkspaceObservationProvider
from .observation import WorkspaceObservationProcessResult
from .observation import WorkspaceObservationProcessRunner
from .provision_credential_claims import IssuedRepositoryProvisionCredential
from .provision_credential_claims import REPOSITORY_PROVISION_CREDENTIAL_SCHEMA_VERSION
from .provision_credential_claims import REPOSITORY_PROVISION_PROTOCOLS
from .provision_credential_claims import RepositoryProvisionCredentialClaims
from .provision_credential_issuance import RepositoryProvisionCredentialIssueRequest
from .provision_credential_issuance import RepositoryProvisionCredentialIssuanceStore
from .repository_storage import DurableLfsObjectStore
from .repository_storage import DurableRepositoryRootManager
from .repository_storage import DurableRootFact
from .repository_storage import LfsObjectMismatchError
from .repository_storage import RepositoryBaseCommitError
from .repository_storage import RepositoryIdentityMismatchError
from .repository_storage import RepositoryRootBoundary
from .repository_storage import RepositoryRootRejectedError
from .repository_storage import RepositoryStorageError
from .sqlite_lfs_repository import GitLfsPolicyError
from .sqlite_lfs_repository import GitLfsQuotaExceededError
from .sqlite_lfs_repository import GitLfsRepository
from .sqlite_lfs_repository import GitLfsRepositoryError
from .work_products import GitLfsClosureError
from .work_products import GitLfsGarbageCollector
from .work_products import GitLfsGitReader
from .work_products import GitLfsOversizedBlobError
from .work_products import GitLfsPointerError
from .work_products import GitLfsPrivateReachabilityFinalizer
from .work_products import GitLfsPublicationManifestPolicyValidator
from .work_products import GitLfsRepositoryBundle
from .work_products import GitLfsRevisionReader
from .work_products import GitLfsWorkProductError
from .work_products import PublicationManifestValidation
from .work_products import RevisionGitAttributes
from .work_products import publication_authorization_scope_digest
from .workspace_lifecycle_mechanism import AgentGitWorkspaceProvisioningMechanism
from .workspace_lifecycle_mechanism import (
    AgentGitWorkspaceProvisioningMechanismError,
)
from .workspace_lifecycle_mechanism import AgentGitWorkspaceRecoveryMechanism
from .workspace_lifecycle_mechanism import AgentGitWorkspaceRecoveryProbe
from .workspace_lifecycle_mechanism import AgentWorkspaceVolumeAllocatorPort
from .workspace_lifecycle_mechanism import expected_volume_labels
from .workspace_lifecycle_mechanism import require_exact_volume_owner
from .workspace_status import AgentGitWorkspaceStatusError
from .workspace_status import AgentGitWorkspaceStatusMechanism
from .workspace_status import WORKSPACE_STATUS_SCRIPT
from .workspace_status import parse_workspace_status_output
from .ref_policy import GitRefAclValidator
from .ref_policy import GitRefUpdate
from .ref_policy import HOST_PUBLICATION_REF_OWNER
from .ref_policy import MIGRATION_HISTORICAL_REF_OWNER
from .ref_policy import RepositoryCredentialClaimsView
from .ref_policy import RepositoryCredentialProtocol
from .ref_policy import RepositoryOwnerRefService
from .ref_policy import RepositoryRefAclError
from .ref_policy import RepositoryRefOwnerIdentity
from .ref_policy import RepositoryRefOwnerKind
from .ref_policy import RepositoryRefOwnerRejectedError
from .ref_policy import private_ref_prefix
from .retention import PrivateNamespaceReachabilityFinalizer
from .retention import RepositoryPrivateNamespace
from .retention import RepositoryPrivateNamespaceHoldKind
from .retention import RepositoryPrivateNamespaceRetentionService
from .retention import RepositoryPrivateNamespaceStatus
from .retention import RepositoryRetentionError


COMPONENT_ID = "openzyme.workspace.git.lfs"
COMPONENT_KIND = "adapter"
WORKSPACE_BACKEND_ID = "openzyme.workspace.git-lfs@1"
WORKSPACE_BACKEND_CONTRACT_DIGEST = (
    "sha256:e29ccdb9334f40b78f9e7a998ca8ece04c04cc2428c6119987c475e5a7b122f6"
)
WORKSPACE_BACKEND_IMPLEMENTATION_DIGEST = GIT_LFS_COMPONENT_MANIFEST_DIGEST
MIGRATION_STATE = "target_implemented_legacy_callers_pending"


__all__ = [
    "AGENT_GIT_WORKSPACE_OBSERVATION_SCHEMA_VERSION",
    "AGENT_GIT_WORKSPACE_RESTORE_COMPARISON_SCHEMA_VERSION",
    "AGENT_GIT_WORKSPACE_SCHEMA_VERSION",
    "COMPONENT_ID",
    "COMPONENT_KIND",
    "GIT_LFS_BINDING_POLICY_SCHEMA_VERSION",
    "GIT_LFS_CLIENT_QUALIFICATION_SCHEMA_VERSION",
    "GIT_LFS_CLOSURE_MANIFEST_SCHEMA_VERSION",
    "GIT_LFS_CLOSURE_VERIFICATION_SCHEMA_VERSION",
    "GIT_LFS_GC_CANDIDATE_RECEIPT_SCHEMA_VERSION",
    "GIT_LFS_OBJECT_READ_RECEIPT_SCHEMA_VERSION",
    "GIT_LFS_POINTER_VERSION",
    "GIT_LFS_PRIVATE_REACHABILITY_RECEIPT_SCHEMA_VERSION",
    "GIT_LFS_UPLOAD_SESSION_SCHEMA_VERSION",
    "GITLESS_COMPUTE_TREE_RECEIPT_SCHEMA_VERSION",
    "GITLESS_COMPUTE_QUALIFICATION_SCHEMA_VERSION",
    "HOST_PUBLICATION_REF_OWNER",
    "MIGRATION_STATE",
    "MIGRATION_HISTORICAL_REF_OWNER",
    "WORKSPACE_BACKEND_CONTRACT_DIGEST",
    "WORKSPACE_BACKEND_ID",
    "WORKSPACE_BACKEND_IMPLEMENTATION_DIGEST",
    "WORKSPACE_STATUS_SCRIPT",
    "AgentGitDirectoryKind",
    "AgentGitWorkspace",
    "AgentGitWorkspaceBlockerCode",
    "AgentGitWorkspaceBaseCommitDriftError",
    "AgentGitWorkspaceCorruptionError",
    "AgentGitWorkspaceInfrastructureError",
    "AgentGitWorkspaceInvariantError",
    "AgentGitWorkspaceObservationProvider",
    "AgentGitWorkspacePermissionError",
    "AgentGitWorkspaceRecoveryError",
    "AgentGitWorkspaceIdentityDriftKind",
    "AgentGitWorkspaceObservation",
    "AgentGitWorkspaceRepository",
    "AgentGitWorkspaceRepositoryError",
    "AgentGitWorkspaceRestoreComparison",
    "AgentGitWorkspaceStatus",
    "AgentGitWorkspaceVersionConflictError",
    "AgentGitWorkspaceStatusError",
    "AgentGitWorkspaceStatusMechanism",
    "AuthenticatedRepositoryRequest",
    "AgentGitWorkspaceProvisioningError",
    "AgentGitWorkspaceProvisioningMechanism",
    "AgentGitWorkspaceProvisioningMechanismError",
    "AgentGitWorkspaceRecoveryMechanism",
    "AgentGitWorkspaceRecoveryProbe",
    "AgentWorkspaceCloneResult",
    "AgentWorkspaceCloneRunner",
    "AgentWorkspaceVolumeAllocatorPort",
    "CloneCommandExecutor",
    "CloneCommandResult",
    "DurableLfsObjectStore",
    "DurableRepositoryRootManager",
    "DurableRootFact",
    "GitLfsBindingPolicy",
    "GitLfsClientEnvironment",
    "GitLfsClientQualification",
    "GitLfsClientQualificationError",
    "GIT_LFS_QUALIFICATION_OPERATIONS",
    "GitLfsQualificationOperationPort",
    "GitLfsQualificationProbeBridge",
    "GitLfsClosureEntry",
    "GitLfsClosureError",
    "GitLfsClosureManifest",
    "GitLfsClosureVerification",
    "GitLfsGcCandidateReceipt",
    "GitLfsGarbageCollector",
    "GitLfsGitReader",
    "GitLfsObjectReadReceipt",
    "GitLfsNativeClientProbe",
    "GitLfsOversizedBlobError",
    "GitLfsPathRepresentation",
    "GitLfsPathRule",
    "GitLfsPointer",
    "GitLfsPointerError",
    "GitLfsPolicyError",
    "GitLfsPrivateReachabilityReceipt",
    "GitLfsPrivateReachabilityFinalizer",
    "GitLfsPublicationManifestPolicyValidator",
    "GitLfsQuotaExceededError",
    "GitLfsRepository",
    "GitLfsRepositoryBindingMechanism",
    "GitLfsRepositoryError",
    "GitLfsRepositoryBundle",
    "GitLfsRevisionReader",
    "GitLfsRetentionClass",
    "GitLfsUploadSession",
    "GitLfsUploadStatus",
    "GitLfsWorkProductError",
    "GitRefAclValidator",
    "GitRefUpdate",
    "GitlessComputeTreeReceipt",
    "GitlessComputeTreeRequest",
    "GitlessComputeQualification",
    "HmacRepositoryCredentialMaterialAdapter",
    "IssuedRepositoryCredential",
    "IssuedRepositoryProvisionCredential",
    "GitRepositoryLocation",
    "GitRepositoryLocator",
    "GitRevisionBackendError",
    "LocalGitRevisionBackend",
    "LocalGitLfsPreparationCommandPort",
    "LocalIsolatedGitLfsPreparationExecutor",
    "LocalGitlessComputeTreePreparer",
    "LfsObjectMismatchError",
    "LFS_JSON_MEDIA_TYPE",
    "LfsBatchRequest",
    "LfsObjectRequest",
    "LfsVerifyRequest",
    "PodmanAgentWorkspaceCloneRunner",
    "PrivateNamespaceReachabilityFinalizer",
    "PublicationManifestValidation",
    "PodmanAgentGitWorkspaceObservationProvider",
    "RepositoryBaseCommitError",
    "RepositoryCredentialClaimsView",
    "RepositoryCredentialClaims",
    "RepositoryCredentialError",
    "RepositoryCredentialExpiredError",
    "RepositoryCredentialIssueRequest",
    "RepositoryCredentialIssuanceStore",
    "RepositoryCredentialMaterialError",
    "RepositoryCredentialProtocol",
    "RepositoryCredentialRejectedError",
    "RepositoryIdentityMismatchError",
    "RepositoryOwnerRefService",
    "RepositoryPrivateNamespace",
    "RepositoryPrivateNamespaceHoldKind",
    "RepositoryPrivateNamespaceRetentionService",
    "RepositoryPrivateNamespaceStatus",
    "RepositoryRefAclError",
    "RepositoryRefOwnerIdentity",
    "RepositoryRefOwnerKind",
    "RepositoryRefOwnerRejectedError",
    "RepositoryRootBoundary",
    "RepositoryRootRejectedError",
    "RepositoryRetentionError",
    "RepositoryEndpointSettings",
    "RepositoryServicePreflightError",
    "RepositoryTransportDependencies",
    "RepositoryTransportError",
    "RepositoryTransportRequestError",
    "RepositoryStorageError",
    "SubprocessLocalGitLfsPreparationCommandPort",
    "RevisionGitAttributes",
    "REPOSITORY_CREDENTIAL_SCHEMA_VERSION",
    "REPOSITORY_PROVISION_CREDENTIAL_SCHEMA_VERSION",
    "REPOSITORY_PROVISION_PROTOCOLS",
    "RepositoryProvisionCredentialClaims",
    "RepositoryProvisionCredentialIssueRequest",
    "RepositoryProvisionCredentialIssuanceStore",
    "WorkspaceObservationProcessResult",
    "WorkspaceObservationProcessRunner",
    "canonical_lfs_digest",
    "canonical_workspace_digest",
    "compare_agent_git_workspace_identity",
    "create_repository_transport_app",
    "expected_volume_labels",
    "qualify_gitless_compute",
    "qualify_native_git_lfs_client",
    "private_ref_prefix",
    "parse_workspace_status_output",
    "publication_authorization_scope_digest",
    "require_repository_path",
    "require_exact_volume_owner",
]
