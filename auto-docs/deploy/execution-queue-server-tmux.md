# Deploy Queue Server on DO via tmux send-keys

> Verified 2026-04-13 on DO droplet `ubuntu-s-1vcpu-1gb-amd-sfo3-01` (137.184.225.153).
> Uses `/home/b/p/all-my-tiny-projects/do-automation/` tools for firewall and SSH.

## Context

The queue server (`server.py`) is the single public TCP endpoint. It runs on the DO droplet, listens on `:9999`, stores jobs in `jobs.db`. All workers and Android apps connect to it. It must start before anything else.

## Prerequisites

- DO droplet is running (`doctl compute droplet list`)
- Your IP is in the DO firewall
- SSH access via `sshpass` + `dopass` file or SSH key

## Identity

```
machine:    DO droplet 527176969 (137.184.225.153)
session:    queue (tmux on the droplet)
port:       :9999 (TCP, 4-byte len + JSON)
database:   /root/simple-tcp-comm/jobs.db
repo:       /root/simple-tcp-comm (git clone)
```

## Step 0: Ensure your IP is in the firewall

```bash
# Check your current IP
curl -s ifconfig.me

# List firewalls to get the ID
/home/b/p/all-my-tiny-projects/do-automation/do-firewall list

# Add your IP (replace <FW_ID> and <YOUR_IP>)
/home/b/p/all-my-tiny-projects/do-automation/do-firewall add-ip <FW_ID> <YOUR_IP>
```

Actual example from 2026-04-12:

```bash
/home/b/p/all-my-tiny-projects/do-automation/do-firewall add-ip 7382692d-a9c1-47b7-88a2-6e659d1be865 217.22.135.247
```

## Step 1: Check if server is already running

```bash
DO_DROPLET=ubuntu-s-1vcpu-1gb-amd-sfo3-01 \
DO_SSH_PASS_FILE=/home/b/dopass \
/home/b/p/all-my-tiny-projects/do-automation/job-queue/deploy-queue status
```

If `RUNNING` — you're done. If `NOT RUNNING` — continue.

## Step 2: Start the server (using deploy-queue)

```bash
# Option A: setup + start (first time or after droplet rebuild)
DO_DROPLET=ubuntu-s-1vcpu-1gb-amd-sfo3-01 \
DO_SSH_PASS_FILE=/home/b/dopass \
/home/b/p/all-my-tiny-projects/do-automation/job-queue/deploy-queue setup

DO_DROPLET=ubuntu-s-1vcpu-1gb-amd-sfo3-01 \
DO_SSH_PASS_FILE=/home/b/dopass \
/home/b/p/all-my-tiny-projects/do-automation/job-queue/deploy-queue start

# Option B: just start (repo already cloned)
DO_DROPLET=ubuntu-s-1vcpu-1gb-amd-sfo3-01 \
DO_SSH_PASS_FILE=/home/b/dopass \
/home/b/p/all-my-tiny-projects/do-automation/job-queue/deploy-queue start
```

What `deploy-queue start` does on the droplet:

```bash
# (executed remotely by deploy-queue)
tmux kill-session -t queue 2>/dev/null || true
tmux new-session -d -s queue -c /root/simple-tcp-comm 'python3 server.py 9999'
```

## Step 2 (alternative): Manual tmux send-keys via SSH

If you prefer explicit control instead of `deploy-queue`:

```bash
# SSH helper
DO_SSH="sshpass -p $(head -1 /home/b/dopass) ssh -o StrictHostKeyChecking=accept-new root@137.184.225.153"

# Clone or update repo
${DO_SSH} "
  if [ -d /root/simple-tcp-comm ]; then
    cd /root/simple-tcp-comm && git pull
  else
    git clone https://github.com/berstearns/simple-tcp-comm.git /root/simple-tcp-comm
  fi
"

# Create tmux session and start server via send-keys
${DO_SSH} "
  tmux kill-session -t queue 2>/dev/null
  tmux new-session -d -s queue -n server -c /root/simple-tcp-comm
  tmux send-keys -t queue:server 'python3 server.py 9999' C-m
"
```

## Step 3: Verify from your local machine

```bash
# Test TCP connectivity
cd /home/b/simple-tcp-comm && python3 -c "import client; print(client.workers())"

# Expected: {'ok': True, 'workers': [...]}

# Check job counts
python3 client.py ls
```

## Step 4: View server logs remotely

```bash
DO_DROPLET=ubuntu-s-1vcpu-1gb-amd-sfo3-01 \
DO_SSH_PASS_FILE=/home/b/dopass \
/home/b/p/all-my-tiny-projects/do-automation/job-queue/deploy-queue logs
```

Or manually:

```bash
${DO_SSH} "tmux capture-pane -t queue:server -p -S -30"
```

## Step 5: Update code on the droplet

```bash
DO_DROPLET=ubuntu-s-1vcpu-1gb-amd-sfo3-01 \
DO_SSH_PASS_FILE=/home/b/dopass \
/home/b/p/all-my-tiny-projects/do-automation/job-queue/deploy-queue update
```

This does `git pull` + restart.

## Stopping

```bash
DO_DROPLET=ubuntu-s-1vcpu-1gb-amd-sfo3-01 \
DO_SSH_PASS_FILE=/home/b/dopass \
/home/b/p/all-my-tiny-projects/do-automation/job-queue/deploy-queue stop
```

## do-automation tools reference

| Tool | Path | What |
|------|------|------|
| `do-firewall` | `/home/b/p/all-my-tiny-projects/do-automation/do-firewall` | Manage DO firewall rules (add-ip, list, show) |
| `do-ssh` | `/home/b/p/all-my-tiny-projects/do-automation/do-ssh` | SSH wrapper (get-url, list droplets) |
| `deploy-queue` | `/home/b/p/all-my-tiny-projects/do-automation/job-queue/deploy-queue` | Queue-specific deploy (setup, start, stop, status, logs, update) |

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `Connection timed out` from local | IP not in firewall | `do-firewall add-ip <FW_ID> $(curl -s ifconfig.me)` |
| `Connection refused` from local | Server not running | `deploy-queue start` |
| `deploy-queue status` → NOT RUNNING | Crashed or never started | `deploy-queue start` |
| `Permission denied` on SSH | Wrong password or key | Check `/home/b/dopass` or add SSH key to droplet |

## Dependency order

```
Step 0: Firewall (your IP must be allowed)
  ↓
Step 1: Queue server (must be first)
  ↓
Step 2: Workers (poll the queue)
  ↓
Step 3: Archive receiver + drains (push from workers)
  ↓
Step 4: Timeline tracker (reads worker DB)
```
