### dotenv file

To have poetry read the `.env` file, run:

```
poetry self add poetry-dotenv-plugin
```

Secrets:
* `TELEGRAM_TOKEN`: the secret token to manage the bot
* `TG_WEBHOOK_TOKEN`: webhooks will be called at `/tg/{TG_WEBHOOK_TOKEN}`
* `POSTGRES_URL`: postgres url


### poetry

To update the packages with the latest bugfixes (the
versions should remain compatible), run:

```
poetry lock
```

Note that this doesn't actually install the packages. To do so, run:

```
poetry install
```

To update the `poetry.lock` file from `pyproject.toml`, without
updating the versions of packages to their latest version which
complies with the version specs, run:

```
poetry lock --no-update
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
