# Start
1) Fill .env.example and rename to .env
2) Configure commissions in static/commissions.json
3) Configure crypto-wallets addresses in static/crypto.json
4) Start with docker:
```
docker build -t gemups_back
docker run gemups_back
```
