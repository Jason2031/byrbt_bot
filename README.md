# byrbt_bot

byrbt bot

### Dev & Run environment

1. macOS Mojave & Ubuntu 16.04
2. python3
   1. sklearn
   2. pillow
   3. pickle
   4. requests
   5. yaml
3. [transmission-cli](https://cli-ck.io/transmission-cli-user-guide/)

### Usage

```shell
# 1. clone this repo
git clone https://github.com/Jason2031/byrbt_bot.git
cd byrbt_bot

# 2. edit the config file
vim config/config.yml
# provide 'user_name' and 'password' of bt.byr.cn
# you can customize the location tags in config file

# 3. have your transmission-cli installed

# 4. start the script
cd ../src
python3 byrbt_bot.py

# 5. input the commands accordingly
```

### Acknowledgements

**[decaptcha](https://github.com/bumzy/decaptcha)**

