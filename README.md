
# Simple Server Temp Mail with Python

## Dockerized Installation (Coming Soon)

**Status: Under Development**

- Complete Docker containerization is in progress
- Will include Postfix mail server
- One-click deployment
- Simplified configuration
- Expected features:
  - Pre-configured Postfix
  - Integrated webhook
  - Easy environment setup

## Manual Installation

### Prerequisites

- **Domain**: antdev.org
- **DNS Provider**: Cloudflare
- **Server**: Ubuntu VPS
- **Mail Server Software**: Postfix

---

### Step 1: DNS Configuration (Cloudflare)

1. Log in to your Cloudflare account
2. Select your domain (antdev.org)

   **Note**: In all the following steps, replace `antdev.org` with your domain name.

3. Go to the DNS settings
4. Add the following records:
   - MX record:
     - Name: `@`
     - Value: `mail.antdev.org`
     - Priority: 10
   - A record:
     - Name: `mail`
     - Value: `[Your VPS IP address]`
   - TXT record (for SPF):
     - Name: `@`
     - Value: `v=spf1 mx ~all`

---

### Step 2: VPS Setup

1. SSH into your Ubuntu VPS
2. Update the system:
   ```bash
   sudo apt update && sudo apt upgrade -y
   ```
3. Set the hostname:
   ```bash
   sudo hostnamectl set-hostname mail.antdev.org
   ```
4. Update `/etc/hosts`:
   ```bash
   sudo nano /etc/hosts
   ```
   Add: `[Your VPS IP] mail.antdev.org antdev.org`

---

### Step 3: Install and Configure Postfix

1. Install Postfix:
   ```bash
   sudo apt install postfix -y
   ```
2. During installation, choose "Internet Site" and enter "antdev.org" as the system mail name
3. Edit the main Postfix configuration:
   ```bash
   sudo nano /etc/postfix/main.cf
   ```
   Add or modify these lines:
   ```
   myhostname = mail.antdev.org
   mydestination = $myhostname, antdev.org, localhost.$mydomain, localhost
   inet_interfaces = all
   mynetworks = 127.0.0.0/8 [::ffff:127.0.0.0]/104 [::1]/128
   smtpd_recipient_restrictions = permit_mynetworks, reject_unauth_destination
   virtual_alias_domains = antdev.org
   virtual_alias_maps = regexp:/etc/postfix/virtual_regexp
   ```
4. Create and edit the `virtual_regexp` file:
   ```bash
   sudo nano /etc/postfix/virtual_regexp
   ```
   Add this line:
   ```
   /.+@antdev\.org/ catchall@antdev.org
   ```

---

5. Restart Postfix:
   ```bash
   sudo systemctl restart postfix
   ```

---

### Step 4: Configure Postfix to Forward Emails to Webhook

1. Install procmail:
   ```bash
   sudo apt install procmail -y
   ```
2. Create a script to forward emails:

   ```bash
   sudo nano /usr/local/bin/forward-to-webhook.sh
   ```

   Add the following content:

   ```bash
   #!/bin/bash
   sed '/Content-Disposition: attachment/,/^\s*$/d; /Content-Disposition: inline/,/^\s*$/d' | \
   curl -X POST -H "Content-Type: text/plain" -H "X-Secret: 12398" --data-binary @- http://localhost:5000/webhook
   ```

   **Note**: Update the `Secret` to match your website/webhook environment variable

   **Note**: It will forward the email to the webhook URL by default (http://localhost:9169/webhook). If you want to forward it to a different URL, you can change the URL in the script.

3. Make the script executable:
   ```bash
   sudo chmod +x /usr/local/bin/forward-to-webhook.sh
   ```
4. Edit the Postfix aliases file:
   ```bash
   sudo nano /etc/aliases
   ```
   Add this line:
   ```
   catchall: "|/usr/local/bin/forward-to-webhook.sh"
   ```
5. Update the aliases database:
   ```bash
   sudo newaliases
   ```
6. Restart Postfix:
   ```bash
   sudo systemctl restart postfix
   ```

---
