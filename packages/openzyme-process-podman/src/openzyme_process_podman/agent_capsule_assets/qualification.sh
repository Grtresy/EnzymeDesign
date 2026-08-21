#!/bin/sh
set -eu

test "$(id -u)" = "10001"
test "$(id -g)" = "10001"
test "${HOME}" = "/home/openzyme"
test "$(pwd)" = "/workspace/repository"

for binary in bash cat cp curl find git git-lfs grep mkdir mv python3 rsync scp sed ssh tar; do
    command -v "${binary}" >/dev/null
done

require_package_version() {
    package_name="$1"
    expected_version="$2"
    actual_version="$(dpkg-query -W -f='${Version}' "${package_name}")"
    test "${actual_version}" = "${expected_version}"
}

require_package_version git '1:2.39.5-0+deb12u2'
require_package_version git-lfs '3.3.0-1+b5'
require_package_version openssh-client '1:9.2p1-2+deb12u7'
require_package_version rsync '3.2.7-1+deb12u2'
require_package_version curl '7.88.1-10+deb12u14'
require_package_version python3 '3.11.2-1+b1'

python3 -c 'from openzyme_execution_sdk import workspace_revision; from openzyme_execution_sdk.client import supervised_sandbox_mode; assert supervised_sandbox_mode() is False'

git --version
git lfs version
ssh -V
rsync --version | sed -n '1p'
scp -V 2>&1 | sed -n '1p'
curl --version | sed -n '1p'

test ! -e /host
test ! -e /run/host
test ! -e /home/openzyme/.ssh
test ! -e /workspace/repository/.git

qualification_root="$(mktemp -d /tmp/openzyme-capsule-qualification.XXXXXX)"
trap 'rm -rf "${qualification_root}"' EXIT HUP INT TERM
git -C "${qualification_root}" init --object-format=sha1
git -C "${qualification_root}" lfs install --local
test "$(git -C "${qualification_root}" rev-parse --git-dir)" = ".git"
test "$(git -C "${qualification_root}" config --local --get filter.lfs.process)" = "git-lfs filter-process"
