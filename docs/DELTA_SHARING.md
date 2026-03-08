# Delta Sharing for Airport Digital Twin

This document describes how to expose the Airport Digital Twin lakehouse tables to other Databricks workspaces using Delta Sharing.

## Overview

Delta Sharing is an open protocol for secure real-time exchange of large datasets. It enables:
- **Cross-workspace sharing** within the same organization
- **Cross-organization sharing** with external partners
- **Cross-cloud sharing** (AWS ↔ Azure ↔ GCP)

## Current Environment

| Property | Value |
|----------|-------|
| **Metastore** | `metastore_aws_us_east_1` |
| **Global Metastore ID** | `aws:us-east-1:c0da88f1-c020-4992-b8c9-c828e556889d` |
| **Delta Sharing Scope** | `INTERNAL_AND_EXTERNAL` |
| **Organization Name** | `databricks-vending-machine` |
| **Token Lifetime** | 90 days (7,776,000 seconds) |

## Tables Available for Sharing

All tables in `serverless_stable_3n0ihb_catalog.airport_digital_twin`:

| Table | Type | Description | Update Frequency |
|-------|------|-------------|------------------|
| `flight_status_gold` | MANAGED | Current flight positions | Real-time (30s) |
| `flight_positions_history` | MANAGED | Historical trajectory data | Append-only |
| `weather_observations` | MANAGED | METAR weather data | Every 15 min |
| `flight_schedule` | MANAGED | FIDS arrival/departure | Every 5 min |
| `baggage_events` | MANAGED | Baggage tracking events | Real-time |
| `gse_status` | MANAGED | Ground support equipment | Every 1 min |

## Sharing Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    PROVIDER WORKSPACE (This)                        │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  Unity Catalog: serverless_stable_3n0ihb_catalog            │   │
│  │  Schema: airport_digital_twin                                │   │
│  │  ├── flight_status_gold                                     │   │
│  │  ├── flight_positions_history                               │   │
│  │  ├── weather_observations                                   │   │
│  │  ├── flight_schedule                                        │   │
│  │  ├── baggage_events                                         │   │
│  │  └── gse_status                                             │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                           │                                         │
│                           ▼                                         │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  SHARE: airport_digital_twin_share                          │   │
│  │  (Contains references to tables with optional aliases)       │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                           │                                         │
│                           ▼                                         │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  RECIPIENT: target_workspace_recipient                       │   │
│  │  (Databricks-to-Databricks or Open Sharing)                  │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                           │
                           │ Delta Sharing Protocol
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   RECIPIENT WORKSPACE                                │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  CATALOG (created from share)                                │   │
│  │  ├── flight_data (alias for flight_status_gold)              │   │
│  │  ├── trajectory_history                                      │   │
│  │  └── ...                                                     │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

## Step-by-Step Setup

### Prerequisites

1. **Metastore Admin** or **CREATE SHARE** privilege on the metastore
2. **USE CATALOG** and **USE SCHEMA** on the source catalog/schema
3. **SELECT** privilege on tables to share

### Step 1: Create a Share

```sql
-- In Databricks SQL or Notebook
CREATE SHARE IF NOT EXISTS airport_digital_twin_share
COMMENT 'Real-time flight data, weather, schedule, baggage, and GSE for airport digital twin';
```

Or via REST API:
```bash
curl -X POST \
  "https://<workspace>/api/2.1/unity-catalog/shares" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "name": "airport_digital_twin_share",
    "comment": "Real-time flight data for airport digital twin demo"
  }'
```

### Step 2: Add Tables to Share

```sql
-- Add all tables to the share
ALTER SHARE airport_digital_twin_share
ADD TABLE serverless_stable_3n0ihb_catalog.airport_digital_twin.flight_status_gold
AS airport_digital_twin.flight_positions;

ALTER SHARE airport_digital_twin_share
ADD TABLE serverless_stable_3n0ihb_catalog.airport_digital_twin.flight_positions_history
AS airport_digital_twin.trajectory_history;

ALTER SHARE airport_digital_twin_share
ADD TABLE serverless_stable_3n0ihb_catalog.airport_digital_twin.weather_observations
AS airport_digital_twin.weather;

ALTER SHARE airport_digital_twin_share
ADD TABLE serverless_stable_3n0ihb_catalog.airport_digital_twin.flight_schedule
AS airport_digital_twin.schedule;

ALTER SHARE airport_digital_twin_share
ADD TABLE serverless_stable_3n0ihb_catalog.airport_digital_twin.baggage_events
AS airport_digital_twin.baggage;

ALTER SHARE airport_digital_twin_share
ADD TABLE serverless_stable_3n0ihb_catalog.airport_digital_twin.gse_status
AS airport_digital_twin.gse;
```

### Step 3: Create a Recipient

#### Option A: Databricks-to-Databricks (Recommended for internal sharing)

```sql
-- Create recipient using the target workspace's global metastore ID
CREATE RECIPIENT IF NOT EXISTS target_workspace_recipient
USING ID 'aws:us-east-1:<target-metastore-id>';
```

To find a workspace's metastore ID:
```sql
-- Run this on the TARGET workspace
SELECT current_metastore();
-- Or use: /api/2.1/unity-catalog/metastore_summary
```

#### Option B: Open Sharing (For non-Databricks recipients)

```sql
-- Create recipient with activation link
CREATE RECIPIENT IF NOT EXISTS external_partner_recipient;

-- Get the activation link
DESCRIBE RECIPIENT external_partner_recipient;
-- Copy the activation_link for the recipient
```

### Step 4: Grant Share Access to Recipient

```sql
GRANT SELECT ON SHARE airport_digital_twin_share
TO RECIPIENT target_workspace_recipient;
```

### Step 5: Access Shared Data (Recipient Side)

On the **recipient workspace**:

```sql
-- Create a catalog from the share
CREATE CATALOG IF NOT EXISTS airport_data_shared
USING SHARE `databricks-vending-machine`.airport_digital_twin_share;

-- Query the shared data
SELECT * FROM airport_data_shared.airport_digital_twin.flight_positions
WHERE on_ground = false
LIMIT 10;
```

## API Reference

### List Shares
```bash
curl -X GET "https://<workspace>/api/2.1/unity-catalog/shares" \
  -H "Authorization: Bearer $TOKEN"
```

### Get Share Details
```bash
curl -X GET "https://<workspace>/api/2.1/unity-catalog/shares/<share_name>" \
  -H "Authorization: Bearer $TOKEN"
```

### Update Share (Add Table)
```bash
curl -X PATCH "https://<workspace>/api/2.1/unity-catalog/shares/<share_name>" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "updates": [{
      "action": "ADD",
      "data_object": {
        "data_object_type": "TABLE",
        "name": "catalog.schema.table",
        "shared_as": "schema.alias"
      }
    }]
  }'
```

### List Recipients
```bash
curl -X GET "https://<workspace>/api/2.1/unity-catalog/recipients" \
  -H "Authorization: Bearer $TOKEN"
```

### Create Databricks-to-Databricks Recipient
```bash
curl -X POST "https://<workspace>/api/2.1/unity-catalog/recipients" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "name": "recipient_name",
    "data_recipient_global_metastore_id": "aws:us-east-1:<metastore-id>",
    "comment": "Description"
  }'
```

### Grant Share to Recipient
```bash
curl -X PATCH "https://<workspace>/api/2.1/unity-catalog/shares/<share_name>/permissions" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "changes": [{
      "principal": "recipient_name",
      "add": ["SELECT"]
    }]
  }'
```

## Sharing Patterns

### Pattern 1: Cross-Workspace (Same Organization)

Best for sharing between dev/staging/prod or between different teams.

```
Provider Metastore ─────► Recipient Metastore
(Same Unity Catalog region preferred for lower latency)
```

### Pattern 2: Cross-Cloud Sharing

```
AWS Workspace ─────► Azure Workspace
                └──► GCP Workspace
```

Note: Cross-cloud sharing has higher latency due to data transfer.

### Pattern 3: Federated Data Mesh

```
Domain A Workspace ────┐
Domain B Workspace ────┼──► Central Analytics Workspace
Domain C Workspace ────┘
```

## Security Considerations

1. **Access Control**: Recipients only see data in granted shares
2. **No Data Copy**: Data stays in provider's storage; only metadata is shared
3. **Audit Trail**: All access is logged in Unity Catalog audit logs
4. **Token Expiration**: Tokens expire after 90 days (configurable)
5. **Revocation**: Access can be revoked instantly by removing recipient grants

## Monitoring Shared Data Access

```sql
-- Query audit logs for share access
SELECT
  event_time,
  user_identity.email,
  action_name,
  request_params.share_name,
  response.status_code
FROM system.access.audit
WHERE action_name LIKE '%Share%'
ORDER BY event_time DESC
LIMIT 100;
```

## Troubleshooting

### Permission Denied on CREATE SHARE
You need `CREATE SHARE` privilege on the metastore. Contact your metastore admin:
```sql
GRANT CREATE SHARE ON METASTORE TO `user@domain.com`;
```

### Recipient Cannot See Share
1. Verify the share grant: `SHOW GRANTS ON SHARE <share_name>`
2. Check recipient's metastore ID matches
3. Ensure recipient has `CREATE CATALOG` privilege

### Stale Data
Delta Sharing provides near-real-time access. If data appears stale:
1. Check source table's last update time
2. Recipient should run `REFRESH` on the catalog

## Next Steps

1. **Request CREATE SHARE privilege** from metastore admin
2. **Identify target workspaces** and collect their metastore IDs
3. **Define sharing scope** (which tables, which recipients)
4. **Set up monitoring** for shared data access

## References

- [Delta Sharing Documentation](https://docs.databricks.com/en/data-sharing/index.html)
- [Unity Catalog Shares API](https://docs.databricks.com/api/workspace/shares)
- [Delta Sharing Protocol](https://github.com/delta-io/delta-sharing)
