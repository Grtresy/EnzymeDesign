#!/bin/sh
# Canonical Git/LFS Adapter hook asset; installed only by operator-controlled setup.
set -eu

reject() {
    printf '%s\n' "OpenZyme repository ACL rejected push: $1" >&2
    exit 1
}

[ "${OPENZYME_REPOSITORY_ACTOR_KIND:-}" = "agent" ] || reject "unsupported actor"
[ -n "${OPENZYME_REPOSITORY_ID:-}" ] || reject "missing repository identity"
[ -n "${OPENZYME_BINDING_ID:-}" ] || reject "missing binding identity"
[ -n "${OPENZYME_BINDING_VERSION:-}" ] || reject "missing binding version"
[ -n "${OPENZYME_PRIVATE_REF_PREFIX:-}" ] || reject "missing private namespace"
[ -x "${OPENZYME_GIT_EXECUTABLE:-}" ] || reject "missing Git executable"

configured_repository_id=$("$OPENZYME_GIT_EXECUTABLE" config --get openzyme.repositoryId)
[ "$configured_repository_id" = "$OPENZYME_REPOSITORY_ID" ] || reject "repository identity mismatch"

case "${OPENZYME_OBJECT_FORMAT:-}" in
    sha1) zero_oid=0000000000000000000000000000000000000000 ;;
    sha256) zero_oid=0000000000000000000000000000000000000000000000000000000000000000 ;;
    *) reject "unsupported object format" ;;
esac
update_count=0
while read -r old_oid new_oid ref_name
do
    update_count=$((update_count + 1))
    [ "$update_count" -eq 1 ] || reject "one ref update is allowed per push"
    case "$ref_name" in
        "$OPENZYME_PRIVATE_REF_PREFIX"/*) ;;
        *) reject "ref is outside the exact private namespace" ;;
    esac
    [ "$new_oid" != "$zero_oid" ] || reject "agent ref deletion is forbidden"
    object_type=$("$OPENZYME_GIT_EXECUTABLE" cat-file -t "$new_oid") \
        || reject "ref target is not a commit object"
    [ "$object_type" = "commit" ] || reject "ref target is not a commit object"
    if [ "$old_oid" != "$zero_oid" ]; then
        "$OPENZYME_GIT_EXECUTABLE" merge-base --is-ancestor "$old_oid" "$new_oid" \
            || reject "agent ref update is not fast-forward"
    fi
done

[ "$update_count" -eq 1 ] || reject "push contains no ref update"
