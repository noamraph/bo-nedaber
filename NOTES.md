### dotenv file

Secrets:
* `TELEGRAM_TOKEN`: the secret token to manage the bot
* `TG_WEBHOOK_TOKEN`: webhooks will be called at `/tg/{TG_WEBHOOK_TOKEN}`
* `POSTGRES_URL`: postgres url



### See it working

```
sudo apt install postgresql postgresql-client
sudo -u postgres createuser --interactive  # Create a user with your username, answer 'y' to superuser
sudo -u postgres createdb USERNAME  # your username

./alem upgrade head

just run

# And in another tab:
just proxy
```


### alembic

Update to the latest revision:

```
./alem upgrade head
```

Get current revision:

```
./alem current
```

Show the history (`-i` means "indicate current"):

```
./alem history -i
```

Downgrade from the latest version:

```
./alem downgrade head-1
```

Delete everything, going to the first (empty) revision:

```
./alem downgrade head
```
