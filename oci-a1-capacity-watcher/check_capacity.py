#!/usr/bin/env python3
import json
import os
import sys
from datetime import datetime, timezone

import oci


SHAPE = os.getenv("OCI_SHAPE", "VM.Standard.A1.Flex")
OCPUS = float(os.getenv("OCI_OCPUS", "2"))
MEMORY_GB = float(os.getenv("OCI_MEMORY_GB", "12"))
AVAILABILITY_DOMAIN = os.getenv("OCI_AVAILABILITY_DOMAIN", "rbVX:ME-DUBAI-1-AD-1")
FAULT_DOMAINS = [
    item.strip()
    for item in os.getenv(
        "OCI_FAULT_DOMAINS",
        "FAULT-DOMAIN-1,FAULT-DOMAIN-2,FAULT-DOMAIN-3",
    ).split(",")
    if item.strip()
]


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable is missing: {name}")
    return value


def write_github_output(name: str, value: str) -> None:
    output_path = os.getenv("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def main() -> int:
    tenancy = require_env("OCI_TENANCY_OCID")
    user = require_env("OCI_USER_OCID")
    fingerprint = require_env("OCI_FINGERPRINT")
    private_key = require_env("OCI_PRIVATE_KEY")
    region = os.getenv("OCI_REGION", "me-dubai-1").strip() or "me-dubai-1"

    config = {
        "user": user,
        "fingerprint": fingerprint,
        "tenancy": tenancy,
        "region": region,
        "key_content": private_key,
    }
    oci.config.validate_config(config)
    compute = oci.core.ComputeClient(config)

    requests = []
    for fault_domain in FAULT_DOMAINS:
        requests.append(
            oci.core.models.CreateCapacityReportShapeAvailabilityDetails(
                instance_shape=SHAPE,
                fault_domain=fault_domain,
                instance_shape_config=oci.core.models.CapacityReportInstanceShapeConfig(
                    ocpus=OCPUS,
                    memory_in_gbs=MEMORY_GB,
                ),
            )
        )

    details = oci.core.models.CreateComputeCapacityReportDetails(
        compartment_id=tenancy,
        availability_domain=AVAILABILITY_DOMAIN,
        shape_availabilities=requests,
    )

    response = compute.create_compute_capacity_report(details)
    report = response.data

    results = []
    available_fault_domains = []
    for item in report.shape_availabilities:
        status = item.availability_status
        count = item.available_count
        fault_domain = item.fault_domain or "UNSPECIFIED"
        if status == "AVAILABLE" and (count is None or count >= 1):
            available_fault_domains.append(fault_domain)
        results.append(
            {
                "fault_domain": fault_domain,
                "availability_status": status,
                "available_count": count,
            }
        )

    available = bool(available_fault_domains)
    checked_at = datetime.now(timezone.utc).isoformat()

    payload = {
        "checked_at_utc": checked_at,
        "region": region,
        "availability_domain": AVAILABILITY_DOMAIN,
        "shape": SHAPE,
        "ocpus": OCPUS,
        "memory_gb": MEMORY_GB,
        "available": available,
        "available_fault_domains": available_fault_domains,
        "results": results,
    }

    print(json.dumps(payload, indent=2))

    with open("capacity-report.json", "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")

    lines = [
        "## OCI A1 capacity watcher",
        "",
        f"- Checked: `{checked_at}`",
        f"- Region: `{region}`",
        f"- Availability domain: `{AVAILABILITY_DOMAIN}`",
        f"- Shape: `{SHAPE}`",
        f"- Requested: **{OCPUS:g} OCPU / {MEMORY_GB:g} GB RAM**",
        "",
        "### Fault-domain results",
        "",
    ]
    for result in results:
        lines.append(
            f"- **{result['fault_domain']}**: `{result['availability_status']}` "
            f"(available count: `{result['available_count']}`)"
        )

    if available:
        lines.extend(
            [
                "",
                "### Capacity is available",
                "",
                "Try creating the saved OCI stack/instance promptly. A capacity report is a point-in-time signal and does not reserve capacity.",
                "",
                "Available fault domain(s): " + ", ".join(f"`{fd}`" for fd in available_fault_domains),
            ]
        )
    else:
        lines.extend(
            [
                "",
                "No matching capacity is available right now. The watcher will check again on the next scheduled run.",
            ]
        )

    with open("capacity-report.md", "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")

    write_github_output("available", "true" if available else "false")
    write_github_output("available_fault_domains", ",".join(available_fault_domains))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"Capacity check failed: {exc}", file=sys.stderr)
        raise
