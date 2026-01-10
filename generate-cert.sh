#!/bin/bash
# Generate a self-signed SSL certificate for local HTTPS

CERT_DIR="./certs"
mkdir -p "$CERT_DIR"

# Generate private key and certificate
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout "$CERT_DIR/key.pem" \
    -out "$CERT_DIR/cert.pem" \
    -subj "/CN=home-inventory/O=Local/C=US" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1,IP:$(hostname -I 2>/dev/null | awk '{print $1}' || echo '192.168.1.100')"

echo ""
echo "✅ Certificates generated in $CERT_DIR/"
echo ""
echo "To use: docker-compose up -d"
echo "Access at: https://<your-ip>:4269"
echo ""
echo "⚠️  Your browser will show a security warning - click 'Advanced' → 'Proceed' to accept the self-signed certificate."

