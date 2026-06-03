# Assignment Policy System

## Overview

The Assignment Policy System automatically generates and manages assignment policies that connect permissions policies with member policies through security groups. This system ensures that when security groups or member policies change, the corresponding assignment policies are automatically updated to maintain the correct relationships.

## How It Works

### Current System Flow
1. **Member Policies** define users and their security group assignments
2. **Security Group Policies** define which permissions are available to each group
3. **Permissions Policies** define the actual permissions and field access rights
4. **Assignment Policies** (NEW) automatically connect permissions to members through security groups

### Assignment Policy Structure
```json
{
  "assignment": {
    "permissions": "permission_policy_id",
    "members": ["member_public_key_1", "member_public_key_2"],
    "security_group": "group_name",
    "description": "Auto-generated assignment for group_name group"
  }
}
```

## Automatic Generation

The system automatically generates assignment policies when:

1. **Member Policy Changes**: When a member's security group assignment changes
2. **Security Group Changes**: When a security group's permissions change
3. **Permissions Policy Changes**: When permissions are modified

### Trigger Points
- Policy submission for `member_policy`
- Policy submission for `securitygroup_policy`
- Policy submission for `permissions_policy`

## API Endpoints

### Backend Endpoints

#### `POST /regenerate-assignments`
Regenerate assignment policies for a specific security group or all security groups.

**Request Body:**
```json
{
  "node": "node_address",
  "security_group": "group_name"  // Optional, if not provided regenerates all
}
```

#### `POST /assignment-summary`
Get a summary of all assignment policies.

**Request Body:**
```json
{
  "node": "node_address"
}
```

#### `POST /handle-member-change`
Handle changes to member policies.

**Request Body:**
```json
{
  "node": "node_address",
  "member_pubkey": "member_public_key",
  "new_security_groups": ["group1", "group2"]
}
```

#### `POST /handle-security-group-change`
Handle changes to security group policies.

**Request Body:**
```json
{
  "node": "node_address",
  "security_group": "group_name"
}
```

## Frontend Integration

### AssignmentManager Component
The frontend includes an `AssignmentManager` component that provides:

1. **Summary View**: Shows total assignments, assignments by security group, and assignments by permission
2. **Regeneration Controls**: Buttons to regenerate all assignments or by specific security group
3. **Real-time Updates**: Automatic refresh after operations

### Usage
```jsx
import AssignmentManager from '../components/AssignmentManager';

// In your component
<AssignmentManager node={nodeAddress} />
```

## Key Functions

### `assignment_manager.py`

#### Core Functions
- `get_all_members_in_security_group(node, security_group)`: Get all member public keys in a security group
- `get_permissions_for_security_group(node, security_group)`: Get all permissions for a security group
- `create_assignment_policy(node, permissions_name, member_pubkeys, security_group, description)`: Create a new assignment policy
- `regenerate_assignments_for_security_group(node, security_group)`: Regenerate all assignments for a security group
- `regenerate_all_assignments(node)`: Regenerate all assignment policies
- `handle_member_policy_change(node, member_pubkey, new_security_groups)`: Handle member policy changes
- `handle_security_group_change(node, security_group)`: Handle security group changes
- `get_assignment_summary(node)`: Get summary of all assignments

## Testing

### Test Script
Run the test script to verify the system works:

```bash
cd policy-gui-be
python test_assignment_system.py
```

### Manual Testing
1. Create a member policy with a security group
2. Create a security group policy with permissions
3. Create a permissions policy
4. Submit these policies and check that assignment policies are automatically generated
5. Use the AssignmentManager component to view and manage assignments

## Error Handling

The system includes comprehensive error handling:

1. **Graceful Degradation**: If assignment generation fails, the main policy submission still succeeds
2. **Logging**: All operations are logged for debugging
3. **Validation**: Assignment policies are validated before submission
4. **Rollback**: Failed operations don't leave the system in an inconsistent state

## Configuration

### Template Configuration
The assignment policy template is located at `templates/assignment_policy.json` and can be customized as needed.

### Automatic Triggers
The system automatically triggers assignment regeneration when:
- Member policies are submitted
- Security group policies are submitted  
- Permissions policies are submitted

## Monitoring

### Assignment Summary
The system provides detailed summaries including:
- Total number of assignments
- Assignments by security group
- Assignments by permission
- Member counts per permission

### Logging
All assignment operations are logged with appropriate detail levels for monitoring and debugging.

## Troubleshooting

### Common Issues

1. **No assignments generated**: Check that security groups have members and permissions
2. **Assignment errors**: Verify that permission policies exist and are valid
3. **Missing members**: Ensure member policies have valid public keys and security group assignments

### Debug Commands
```python
# Get assignment summary
summary = assignment_manager.get_assignment_summary(node)

# Check specific security group
members = assignment_manager.get_all_members_in_security_group(node, "group_name")
permissions = assignment_manager.get_permissions_for_security_group(node, "group_name")

# Regenerate assignments
assignment_manager.regenerate_assignments_for_security_group(node, "group_name")
```

## Future Enhancements

1. **Bulk Operations**: Support for bulk assignment operations
2. **Assignment Templates**: Customizable assignment templates
3. **Audit Trail**: Track assignment changes over time
4. **Conflict Resolution**: Handle conflicting assignments
5. **Performance Optimization**: Cache frequently accessed data 