#-----------------------------------------------------------------------------------------------------------------------
# Validate if policy exists
#-----------------------------------------------------------------------------------------------------------------------
# process !local_scripts/node-deployment/policies/validate_node_policy.al

on error ignore
if !debug_mode == true then set debug on


if !debug_mode == true then print "check if node policy exists"

:dns-check:
if !enable_dns == true and !external_dns then
<do is_policy = blockchain get !node_type where
    company=!company_name and
    name=!node_name and
    ip = !external_dns and
    port = !anylog_server_port bring.first>
do goto end-script
else if !tcp_bind == true and !overlay_ip then
<do is_policy = blockchain get !node_type where
    company=!company_name and
    name=!node_name and
    ip = !overlay_ip and
    port = !anylog_server_port bring.first>
do goto end-script
else if !tcp_bind == true then
<do is_policy = blockchain get !node_type where
    company=!company_name and
    name=!node_name and
    ip = !ip and
    port = !anylog_server_port bring.first>
do goto end-script
else if !tcp_bind == false then
<do is_policy = blockchain get !node_type where
    company=!company_name and
    name=!node_name and
    ip = !external_ip and
    local_ip = !ip and
    port = !anylog_server_port bring.first>
do if not !is_policy and !overlay_ip then goto overlay-fallback
do goto end-script

:overlay-fallback:
# Fallback for Docker deployments where ip=host.docker.internal differs from external_ip
<is_policy = blockchain get !node_type where
    company=!company_name and
    name=!node_name and
    ip = !overlay_ip and
    port = !anylog_server_port bring.first>

:end-script:
end script

