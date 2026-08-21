#!/usr/bin/env bash
# Bootstrap an Oracle Cloud Always Free VM to run the SEO Auditor backend.
# Run ON THE VM, once, as a user with sudo. Idempotent.
set -euo pipefail

echo "==> Installing Docker"
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
  echo "    Added $USER to the docker group -- log out and back in for it to apply."
fi

echo "==> Opening ports 80 and 443 on the instance firewall"
# Oracle's Ubuntu and Oracle Linux images ship with a host firewall that drops
# everything except SSH. Opening the VCN Security List alone is NOT enough --
# this is the single most common reason an OCI deployment is unreachable while
# looking perfectly healthy from inside the VM.
if command -v firewall-cmd >/dev/null 2>&1; then
  sudo firewall-cmd --permanent --add-service=http
  sudo firewall-cmd --permanent --add-service=https
  sudo firewall-cmd --reload
  echo "    firewalld updated."
elif command -v iptables >/dev/null 2>&1; then
  sudo iptables -I INPUT 5 -p tcp --dport 80  -j ACCEPT
  sudo iptables -I INPUT 6 -p tcp --dport 443 -j ACCEPT
  # Persist across reboots, or the rules vanish on the next restart.
  if command -v netfilter-persistent >/dev/null 2>&1; then
    sudo netfilter-persistent save
  else
    sudo apt-get update -qq && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq iptables-persistent
  fi
  echo "    iptables updated and persisted."
fi

echo
echo "==> Host firewall done. You must ALSO allow 80/443 in the VCN Security List:"
echo "    OCI Console -> Networking -> Virtual Cloud Networks -> your VCN"
echo "      -> Security Lists -> Default Security List -> Add Ingress Rules"
echo "      Source 0.0.0.0/0, IP Protocol TCP, Destination Port 80 and 443"
echo
echo "Next:"
echo "  cp deploy/oracle/.env.example deploy/oracle/.env   # then edit it"
echo "  docker compose -f deploy/oracle/docker-compose.yml up -d --build"
