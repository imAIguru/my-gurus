# OCI A1 Capacity Watcher

Checks Oracle Cloud UAE East (Dubai) once per hour for `VM.Standard.A1.Flex` capacity matching **2 OCPU / 12 GB RAM** across `FAULT-DOMAIN-1`, `FAULT-DOMAIN-2`, and `FAULT-DOMAIN-3`.

When capacity is reported as available, the workflow opens a GitHub issue titled:

`OCI A1 AVAILABLE - 2 OCPU / 12 GB in Dubai`

The workflow does **not** create an OCI instance and does not reserve capacity. It is alert-only.

## Required GitHub Actions secrets

Open the repository on GitHub, then go to **Settings > Secrets and variables > Actions > New repository secret** and add these four secrets:

- `OCI_TENANCY_OCID` - tenancy OCID, beginning with `ocid1.tenancy...`
- `OCI_USER_OCID` - OCI user OCID, beginning with `ocid1.user...`
- `OCI_FINGERPRINT` - fingerprint for the OCI API signing key
- `OCI_PRIVATE_KEY` - the complete PEM private API key, including the BEGIN/END PRIVATE KEY lines

Never commit the private key to the repository.

## OCI API key

The GitHub runner needs an OCI API signing key belonging to your OCI user. In OCI Console, open your user/profile security settings, add an API key, and securely save the private key. OCI shows the fingerprint after the public key is registered.

The OCI user must have permission to request Compute capacity reports in the target tenancy/compartment.

## Test it

After all four secrets exist:

1. Open the repository's **Actions** tab.
2. Select **OCI A1 Capacity Watcher**.
3. Choose **Run workflow**.
4. Open the run and inspect **Check Dubai A1 capacity**.

The workflow also stores `capacity-report.json` and `capacity-report.md` as a 7-day Actions artifact.

## Schedule

GitHub Actions runs the watcher hourly at minute 17. Scheduled runs can be delayed during periods of high GitHub Actions load, so this is not a real-time reservation mechanism.
