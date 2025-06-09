from flask import Blueprint, request, jsonify
from services.db import get_connection
import logging

igmp_bp = Blueprint('igmp', __name__)
logger = logging.getLogger(__name__)
group_membership = {}

@igmp_bp.route("/process", methods=["POST"])
def process_igmp():
    data = request.get_json()
    dpid = str(data.get("dpid"))
    in_port = data.get("in_port")
    msgtype = data.get("msgtype")
    address = data.get("address")
    records = data.get("records", [])

    install_flows = set()
    remove_flows = set()

    logger.info(f"IGMP recibido: switch={dpid}, puerto={in_port}, tipo={msgtype}")

    if msgtype == 34:  
        for record in records:
            group_ip = record.get("address")
            record_type = record.get("type")
            sources = record.get("sources", [])

            if record_type in [1, 3]:  
                if not sources:
                    logger.info(f" Ignorado IGMPv3 Join vacío para {group_ip}")
                    continue
                group_membership.setdefault(group_ip, {}).setdefault(dpid, [])
                if in_port not in group_membership[group_ip][dpid]:
                    group_membership[group_ip][dpid].append(in_port)
                    logger.info(f" [JOIN-v3] {group_ip} -> switch {dpid}, port {in_port}")
                    install_flows.add(group_ip)

            elif record_type in [2, 4]:  
                if group_ip in group_membership and dpid in group_membership[group_ip]:
                    if in_port in group_membership[group_ip][dpid]:
                        group_membership[group_ip][dpid].remove(in_port)
                        logger.info(f" [LEAVE-v3] {group_ip} <- switch {dpid}, port {in_port}")
                        if not group_membership[group_ip][dpid]:
                            del group_membership[group_ip][dpid]
                        if not group_membership[group_ip]:
                            del group_membership[group_ip]
                            remove_flows.add(group_ip)

    elif msgtype == 22:  
        group_ip = address
        group_membership.setdefault(group_ip, {}).setdefault(dpid, [])
        old_ports = list(group_membership[group_ip][dpid])

        if in_port not in group_membership[group_ip][dpid]:
            group_membership[group_ip][dpid].append(in_port)
            logger.info(f" [JOIN-v2] {group_ip} -> switch {dpid}, port {in_port}")

        if sorted(old_ports) != sorted(group_membership[group_ip][dpid]):
            install_flows.add(group_ip)


    elif msgtype == 23:  
        group_ip = address
        if group_ip in group_membership and dpid in group_membership[group_ip]:
            if in_port in group_membership[group_ip][dpid]:
                group_membership[group_ip][dpid].remove(in_port)
                logger.info(f" [LEAVE-v2] {group_ip} <- switch {dpid}, port {in_port}")

            if not group_membership[group_ip][dpid]:
                del group_membership[group_ip][dpid]

            if group_ip in group_membership and not any(group_membership[group_ip].values()):
                del group_membership[group_ip]
                remove_flows.add(group_ip)



    return jsonify({
        "group_membership": group_membership,
        "install_flows": list(install_flows),
        "remove_flows": list(remove_flows)
    })