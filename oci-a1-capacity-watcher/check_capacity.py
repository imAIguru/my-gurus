#!/usr/bin/env python3
import json
import os
import sys
from datetime import datetime, timezone

import oci


SHAPE = os.getenv("OCI_SHAPE", "VM.Standard.A1.Flex")
OCPUS = float(os.getenv("OCI_OCPUS", "2"))
MEMORY_GB = float(os.getenv("OCI_MEMORY_GB", "12"))
HOME_REGION = os.getenv("OCI_HOME_REGION", os.getenv("OCI_REGION", "me-dubai-1")).strip() or "me-dubai-1"
PRIORITY_REGIONS = [
    item.strip()
    for item in os.getenv(
        "OCI_PRIORITY_REGIONS",
        "me-riyadh-1,me-jeddah-1,me-dubai-1,me-abudhabi-1,ap-mumbai-1,ap-hyderabad-1",
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


def base_config() -> dict:
    return {
        "user": require_env("OCI_USER_OCID"),
        "fingerprint": require_env("OCI_FINGERPRINT"),
        "tenancy": require_env("OCI_TENANCY_OCID"),
        "region": HOME_REGION,
        "key_content": require_env("OCI_PRIVATE_KEY"),
    }


def ordered_regions(subscriptions):
    ready = [s.region_name for s in subscriptions if s.status == "READY"]
    ready_set = set(ready)
    ordered = [r for r in PRIORITY_REGIONS if r in ready_set]
    ordered.extend(sorted(r for r in ready if r not in set(ordered)))
    return ordered


def check_region(config: dict, tenancy: str, region: str) -> dict:
    region_config = dict(config)
    region_config["region"] = region

    identity = oci.identity.IdentityClient(region_config)
    compute = oci.core.ComputeClient(region_config)

    result = {
        "region": region,
        "available": False,
        "available_locations": [],
        "availability_domains": [],
    }

    ads = identity.list_availability_domains(tenancy).data
    for ad in ads:
        ad_result = {"name": ad.name, "fault_domains": []}
        try:
            fds = identity.list_fault_domains(tenancy, ad.name).data
            fault_domain_names = [fd.name for fd in fds]
        except Exception:
            fault_domain_names = []

        # OCI normally exposes fault domains. If none are returned, ask for
        # availability without pinning to a fault domain.
        targets = fault_domain_names or [None]
        requests = []
        for fault_domain in targets:
            kwargs = {
                "instance_shape": SHAPE,
                "instance_shape_config": oci.core.models.CapacityReportInstanceShapeConfig(
                    ocpus=OCPUS,
                    memory_in_gbs=MEMORY_GB,
                ),
            }
            if fault_domain:
                kwargs["fault_domain"] = fault_domain
            requests.append(
                oci.core.models.CreateCapacityReportShapeAvailabilityDetails(**kwargs)
            )

        details = oci.core.models.CreateComputeCapacityReportDetails(
            compartment_id=tenancy,
            availability_domain=ad.name,
            shape_availabilities=requests,
        )

        response = compute.create_compute_capacity_report(details)
        for item in response.data.shape_availabilities:
            status = item.availability_status
            count = item.available_count
            fault_domain = item.fault_domain or "UNSPECIFIED"
            is_available = status == "AVAILABLE" and (count is None or count >= 1)
            if is_available:
                result["available"] = True
                location = f"{region}/{ad.name}/{fault_domain}"
                result["available_locations"].append(location)
            ad_result["fault_domains"].append(
                {
                    "name": fault_domain,
                    "availability_status": status,
                    "available_count": count,
                }
            )

        result["availability_domains"].append(ad_result)

    return result


def main() -> int:
    config = base_config()
    tenancy = config["tenancy"]
    oci.config.validate_config(config)

    # Region subscriptions are tenancy-wide. Only READY subscriptions can be
    # queried for regional Compute capacity.
    identity_home = oci.identity.IdentityClient(config)
    subscriptions = identity_home.list_region_subscriptions(tenancy).data
    regions = ordered_regions(subscriptions)

    if not regions:
        raise RuntimeError("No READY OCI region subscriptions were found for this tenancy")

    checked_at = datetime.now(timezone.utc).isoformat()
    region_results = []
    available_locations = []

    for region in regions:
        try:
            region_result = check_region(config, tenancy, region)
        except Exception as exc:
            region_result = {
                "region": region,
                "available": False,
                "available_locations": [],
                "availability_domains": [],
                "error": f"{type(exc).__name__}: {exc}",
            }
        region_results.append(region_result)
        available_locations.extend(region_result.get("available_locations", []))

    available = bool(available_locations)
    payload = {
        "checked_at_utc": checked_at,
        "home_region": HOME_REGION,
        "checked_regions": regions,
        "shape": SHAPE,
        "ocpus": OCPUS,
        "memory_gb": MEMORY_GB,
        "available": available,
        "available_locations": available_locations,
        "regions": region_results,
    }

    print(json.dumps(payload, indent=2))

    with open("capacity-report.json", "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")

    lines = [
        "## OCI A1 multi-region capacity watcher",
        "",
        f"- Checked: `{checked_at}`",
        f"- Home region: `{HOME_REGION}`",
        f"- Shape: `{SHAPE}`",
        f"- Requested: **{OCPUS:g} OCPU / {MEMORY_GB:g} GB RAM**",
        f"- READY subscribed regions checked: **{len(regions)}**",
        "",
        "### Region results",
        "",
    ]

    for region_result in region_results:
        region = region_result["region"]
        if region_result.get("error"):
            lines.append(f"- **{region}**: `CHECK_ERROR` - {region_result['error']}")
            continue
        if region_result["available"]:
            lines.append(f"- **{region}**: `AVAILABLE`")
            for location in region_result["available_locations"]:
                lines.append(f"  - `{location}`")
        else:
            lines.append(f"- **{region}**: no matching capacity reported")

    if available:
        lines.extend(
            [
                "",
                "### Capacity is available",
                "",
                "Try creating the instance promptly. Capacity reports are point-in-time signals and do not reserve capacity.",
                "",
            ]
        )
        for location in available_locations:
            lines.append(f"- `{location}`")
    else:
        lines.extend(
            [
                "",
                "No matching capacity is available in the READY subscribed regions right now.",
                "The watcher will check again on the next scheduled run.",
            ]
        )

    with open("capacity-report.md", "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")

    available_regions = sorted({loc.split("/", 1)[0] for loc in available_locations})
    write_github_output("available", "true" if available else "false")
    write_github_output("available_regions", ",".join(available_regions))
    write_github_output("available_locations", ";".join(available_locations))
    write_github_output("checked_regions", ",".join(regions))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"Capacity check failed: {exc}", file=sys.stderr)
        raise
