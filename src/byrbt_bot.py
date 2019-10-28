import argparse
import logging
import os
import pickle
import re
import requests
from io import BytesIO
from urllib.request import urlopen

import yaml
from PIL import Image
from lxml import etree

from decaptcha import DeCaptcha

_BASE_URL = 'https://bt.byr.cn/'
_tag_map = {
    'free': '免费',
    'twoup': '2x上传',
    'twoupfree': '免费&2x上传',
    'halfdown': '50%下载',
    'twouphalfdown': '50%下载&2x上传',
    'thirtypercent': '30%下载',
}
_cat_map = {
    '电影': 'movie',
    '剧集': 'episode',
    '动漫': 'anime',
    '音乐': 'music',
    '综艺': 'show',
    '游戏': 'game',
    '软件': 'software',
    '资料': 'material',
    '体育': 'sport',
    '记录': 'documentary',
}


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', dest='config', default='config/config.yml', type=str,
                        help='the location of config file.')
    return parser.parse_args()


def parse_relative_path(path):
    if os.path.isabs(path):
        return path
    root = '..'
    return os.path.join(os.path.abspath(root), path)


def op_help():
    return """
    byrbt bot: a bot that handles basic usage of bt.byr.cn
    usage:
        1. list - list records based on constraints, 50 records per page
            i.e. ls [-c $cat] [-t $tag] [-p $page]
                $cat - category
                $tag - free/2x upload, etc
                $page - default 0
        
        2. search - search and list records based on constraints, 50 records per page
            i.e. se [-c $cat] [-t $tag] [-p $page] [-i $query]
                $cat - category
                $tag - free/2x upload, etc
                $page - default 0
                $query - search query, must be placed at the end of this operation string
        
        3. download - download and start torrent file
            i.e. dl $id [(-l $loc_name)|(-c $loc)]
                $id - torrent id, acquired by `ls` or `se`
                $loc_name - location predefined in config file
                $loc - custom location, must be absolute path
        
        4. list torrent status - list the torrent files status, merely call `transmission-remote -l` 
            i.e. tls
        
        5. remove torrent - remove specific torrent job, merely call `transmission-remote -t $id -r`
            i.e. trm $torrent_id
        
        6. refresh - refresh cookies
        7. help - print this message
        8. exit
            
    """


class ByrbtBot(object):
    def __init__(self, config):
        logger_loc = parse_relative_path(config['bot_config']['logger_location'])
        if not os.path.exists(logger_loc):
            os.makedirs(logger_loc)
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                            filename=os.path.join(logger_loc, 'info.log'), filemode='a')
        self._logger = logging.getLogger(__name__)

        self._session = requests.session()
        self._session.headers = {
            'User-Agent': 'Magic Browser'
        }

        self._decaptcha = DeCaptcha()
        self._decaptcha.load_model(parse_relative_path(config['bot_config']['model_location']))

        cookie_loc = parse_relative_path(config['bot_config']['cookie_location'])
        if not os.path.exists(cookie_loc):
            os.makedirs(cookie_loc)
        self._cookie_loc = os.path.join(cookie_loc, 'cookie')

        self._seed_path = parse_relative_path(config['bot_config']['torrent']['save_location'])
        if not os.path.exists(self._seed_path):
            os.makedirs(self._seed_path)

        self._delete_after_activation = config['bot_config']['torrent']['delete_after_activation']

        self.config = config

    def _login(self):
        self._logger.info('start login process')

        login_page = self._get_url('login.php')
        image_url = login_page.xpath('//img[@alt="CAPTCHA"]/@src')[0]
        image_file = Image.open(BytesIO(urlopen(_BASE_URL + image_url).read()))
        captcha_text = self._decaptcha.decode(image_file)
        self._logger.debug('captcha text: {}'.format(captcha_text))

        image_hash = login_page.xpath('//input[@name="imagehash"]/@value')[0]
        login_data = {
            'username': self.config['bot_config']['account']['user_name'],
            'password': self.config['bot_config']['account']['password'],
            'imagestring': captcha_text,
            'imagehash': image_hash
        }
        main_page = self._session.post(_BASE_URL + 'takelogin.php', login_data)
        if main_page.url != _BASE_URL + 'index.php':
            self._logger.error('login error')
            return

    def _save_cookies(self):
        self._logger.info('save cookies')
        with open(self._cookie_loc, 'wb') as f:
            pickle.dump(self._session.cookies, f)

    def _load_cookies(self):
        if os.path.exists(self._cookie_loc):
            with open(self._cookie_loc, 'rb') as f:
                self._logger.info('load cookie from file {}'.format(self.config['bot_config']['cookie_location']))
                self._session.cookies = pickle.load(f)
        else:
            self._logger.info('load cookies by login')
            self._login()
            self._save_cookies()

    def _get_url(self, url):
        self._logger.debug('get url: ' + url)
        req = self._session.get(_BASE_URL + url)
        return etree.HTML(req.text, etree.HTMLParser())

    def start(self):
        self._load_cookies()
        print(op_help())
        while True:
            action_str = input()
            if action_str == 'refresh':
                self._logger.info('refresh cookies by login')
                self._login()
                self._save_cookies()
            elif action_str == 'exit':
                break
            elif action_str == 'help':
                print(op_help())
            elif action_str.startswith('ls'):
                self.list(action_str)
            elif action_str.startswith('se'):
                self.search(action_str)
            elif action_str.startswith('dl'):
                self.download_torrent(action_str)
            elif action_str.startswith('tls'):
                self.list_torrent()
            elif action_str.startswith('trm'):
                self.remove_torrent(action_str)
            else:
                print('invalid operation')
                print(op_help())

    def _get_list_url(self, op_str):
        op_str += ' '
        self._logger.debug('list op: {}'.format(op_str))

        cat_str = ''
        cat = re.findall(r'-c (.+?) ', op_str, re.I)
        if len(cat) != 0:
            if self.config['bt_config']['category'][cat[0]] is None:
                self._logger.info('no such category {}, use `all`'.format(cat[0]))
            else:
                cat_str = str(self.config['bt_config']['category'][cat[0]]['all'])

        tag_str = ''
        tag = re.findall(r'-t (.+?) ', op_str, re.I)
        if len(tag) != 0:
            if self.config['bt_config']['tag'][tag[0]] is None:
                self._logger.info('no such tag {}, use `all`'.format(tag[0]))
            else:
                tag_str = str(self.config['bt_config']['tag'][tag[0]])

        page_num_str = '0'
        page_num = re.findall(r'-p (\d+?) ', op_str, re.I)
        if len(page_num) == 0:
            self._logger.info('invalid page param, use `0`')
        else:
            page_num_str = str(page_num[0])

        url = 'torrents.php?'
        if cat_str != '':
            url += 'cat={}&'.format(cat_str)
        if tag_str != '':
            url += 'spstate={}&'.format(tag_str)
        if page_num_str != '':
            url += 'page={}'.format(page_num_str)

        return url

    @staticmethod
    def _get_tag(tag):
        try:
            return _tag_map[tag]
        except KeyError:
            return ''

    def _pretty_print_page(self, url):
        page = self._get_url(url)
        content_list = page.xpath('//table[@class="torrents"]/form/tr')
        for i in range(1, len(content_list)):
            item = content_list[i]
            tds = item.xpath('./td')

            cat = tds[0].xpath('./a/img/@title')[0]

            main_td = tds[1].xpath('./table/tr/td')[0]
            href = main_td.xpath('./a/@href')[0]
            seed_id = re.findall(r'id=(\d+)&', href)[0]
            title = main_td.xpath('./a/b/text()')[0]
            sub = main_td.xpath('./br')
            sub_title = sub[0].tail if len(sub) > 0 else ''
            tags = set(main_td.xpath('./b/font/@class'))
            is_seeding = len(main_td.xpath('./img[@src="pic/seeding.png"]')) > 0
            is_finished = len(main_td.xpath('./img[@src="pic/finished.png"]')) > 0
            is_hot = False
            if 'hot' in tags:
                is_hot = True
                tags.remove('hot')
            tag = ''
            if len(tags) > 0:
                tag = self._get_tag(tags.pop())

            file_size = "{} {}".format(tds[4].xpath('./text()')[0], tds[4].xpath('./br')[0].tail)

            seeding = tds[5].xpath('.//text()')[0]

            downloading = tds[6].xpath('.//text()')[0]

            finished = tds[7].xpath('.//text()')[0]

            pretty_str = '{}.【\033[1;34m{}\033[0m】'.format(i, cat)
            if is_hot:
                pretty_str += '【\033[1;31m热门\033[0m】'
            if tag != '':
                pretty_str += '【\033[1;33m{}\033[0m】'.format(tag)
            if is_seeding:
                pretty_str += '【\033[1;36m做种中\033[0m】'
            if is_finished:
                pretty_str += '【\033[1;36m已完成\033[0m】'
            pretty_str += '\tid: {}\n\t{}'.format(seed_id, title)
            if sub_title != '':
                pretty_str += '\n\t\t{}'.format(sub_title)
            pretty_str += '\n\t\t{}/{}/{}\t{}\n'.format(seeding, downloading, finished, file_size)

            print(pretty_str)

    def list(self, op_str):
        """
        full str: ls [-c $cat] [-t $tag] [-p $page]
        :param op_str: `list` operation string
        :return: nothing, merely print the result based on constraints
        """
        url = self._get_list_url(op_str)
        self._pretty_print_page(url)

    @staticmethod
    def _get_search_query(op_str):
        components = op_str.split(' ')
        if '-i' not in components:
            return ''
        return '+'.join(components[components.index('-i') + 1:])

    def search(self, op_str):
        """
        full str: se [-c $cat] [-t $tag] [-p $page] [-i $query]
        note: -i $query must be the last parameter pair
        :param op_str: `search` operation string
        :return: nothing, merely print the result based on constraints
        """
        url = self._get_list_url(op_str)
        query = self._get_search_query(op_str)
        if query != '':
            url += '&{}'.format(query)
        self._pretty_print_page(url)

    @staticmethod
    def _get_cat(cat):
        try:
            return _cat_map[cat]
        except KeyError:
            return 'default'

    def download_torrent(self, op_str):
        """
        full str: dl $id [(-l $loc_name)|(-c $loc)]
        note: -l means built-in location defined in config file, -c means custom absolute location,
        default location is based on the torrent category
        :param op_str: `download` operation string
        :return: nothing, the result is printed
        """
        id_re = re.findall(r'dl (\d+)', op_str, re.I)
        if len(id_re) == 0:
            print('no such torrent')
            return
        id_str = id_re[0]

        detail_url = 'details.php?id={}'.format(id_str)
        detail_page = self._get_url(detail_url)
        name_element = detail_page.xpath('//td/a[@class="index"]')[0]
        file_name = name_element.xpath('./text()')[0]
        dl_url = _BASE_URL + name_element.xpath('./@href')[0]
        cat = detail_page.xpath('//span[@id="type"]')[0].xpath('./text()')[0]
        cat = self._get_cat(cat)

        loc = re.findall(r' -l (.+)', op_str, re.I)
        if len(loc) != 0:
            try:
                loc_str = self.config['external_config']['torrent_location'][loc[0]]
            except KeyError:
                print('no such predefined location: {}'.format(loc[0]))
                loc_str = ''
        else:
            loc_str = re.findall(r' -c (.+)', op_str, re.I)
        loc_str = os.path.abspath(os.path.expanduser(loc_str))
        if not os.path.isdir(loc_str):
            print('not a dir path: {}, use category default loc'.format(loc_str))
            loc_str = os.path.abspath(os.path.expanduser(self.config['external_config']['torrent_location'][cat]))

        if not os.path.exists(loc_str):
            os.makedirs(loc_str)
        seed_file_path = os.path.join(self._seed_path, file_name)

        r = self._session.get(dl_url)
        with open(seed_file_path, "wb") as f:
            f.write(r.content)

        cmd_str = '{} {} {}'.format(parse_relative_path('script/start_tsm.sh'), seed_file_path, loc_str)
        ret_val = os.system(cmd_str)
        if ret_val != 0:
            self._logger.error('script `{}` returns {}'.format(cmd_str, ret_val))

        if self._delete_after_activation:
            os.system('rm {}'.format(seed_file_path))

    @staticmethod
    def list_torrent():
        os.system('transmission-remote -l')

    @staticmethod
    def remove_torrent(op_str):
        id_re = re.findall(r'trm (\d+)', op_str, re.I)
        if len(id_re) == 0:
            print('no such torrent id')
            return
        id_str = id_re[0]
        os.system('transmission-remote -t {} -r'.format(id_str))


if __name__ == "__main__":
    args = get_args()
    config_location = parse_relative_path(args.config)
    if not os.path.exists(config_location):
        print("FATAL: config file doesn't exist at {}.".format(config_location))
        exit(-1)
    with open(config_location) as f_obj:
        config_obj = yaml.load(f_obj.read())
    if config_obj is None:
        print("FATAL: fail loading config file {}.".format(config_location))

    b = ByrbtBot(config_obj)
    b.start()
