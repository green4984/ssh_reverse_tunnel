# ssh_reverse_tunnel

ssh reverse tunnel use paramiko and run thread as daemon behind main thread

See also: https://github.com/paramiko/paramiko/blob/master/demos/rforward.py

Require paramiko.

# Example
#create ssh reverse object
ssh = None
try:
   ssh = SSHReverse(server='',
                    bind_port=(None, None, None),
                    remote='127.0.0.1:443',
                    username='hello',
                    password='world',
                    key_file=None)
except Exception as e:
   logging.error(e)
   ssh = None
return ssh

#begin create connection to server
ssh.create(timeout=5000, daemon=True, tunnel_close_callback=self.send_signal_recreate)

#close and remove ssh reverse connection
ssh.remove(wait=True)
