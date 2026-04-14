# SSL Certificate Configuration

## Option 1: Let's Encrypt (Recommended for Production)

### Using Certbot (standalone mode)
```bash
# Install certbot
apt-get install certbot

# Generate certificate (stop Nginx first if running)
certbot certonly --standalone -d your-domain.com

# Copy certificates to this directory
cp /etc/letsencrypt/live/your-domain.com/fullchain.pem ./fullchain.pem
cp /etc/letsencrypt/live/your-domain.com/privkey.pem ./privkey.pem

# Set up auto-renewal
certbot renew --dry-run
```

### Using Certbot with Docker
```bash
# Run certbot in Docker
docker run -it --rm \
  -v ./ssl:/etc/letsencrypt \
  -v ./ssl-data:/var/lib/letsencrypt \
  certbot/certbot certonly --standalone -d your-domain.com

# Symlink or copy the generated certificates
ln -s ./ssl/live/your-domain.com/fullchain.pem ./fullchain.pem
ln -s ./ssl/live/your-domain.com/privkey.pem ./privkey.pem
```

## Option 2: Self-Signed Certificate (Development Only)

```bash
# Generate self-signed certificate
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout privkey.pem \
  -out fullchain.pem \
  -subj "/CN=localhost"

# For testing, you may also need:
openssl dhparam -out dhparam.pem 2048
```

## Certificate Files Required

| File | Description |
|------|-------------|
| `fullchain.pem` | Full certificate chain (server cert + intermediate certs) |
| `privkey.pem` | Private key (keep secure, never share) |
| `dhparam.pem` | Diffie-Hellman parameters (optional, for stronger SSL) |

## Security Notes

1. **Never commit private keys to git** - Add `privkey.pem` to .gitignore
2. **Set proper permissions**:
   ```bash
   chmod 600 privkey.pem
   chmod 644 fullchain.pem
   ```
3. **Monitor certificate expiration** - Set up renewal reminders
4. **Use HTTPS redirect** - Uncomment SSL redirect in nginx.conf

## Testing SSL Configuration

```bash
# Test Nginx config
nginx -t

# Test SSL connection
openssl s_client -connect your-domain.com:443 -servername your-domain.com

# Check certificate details
openssl x509 -in fullchain.pem -text -noout
```