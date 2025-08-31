"""GitHub Project Backup tool
"""
import argparse
import configparser
import json
import githubpj


DEFAULT_CONFIG_FILE = 'backup.conf'


def main(config):
    gp = githubpj.GitHubPj(config)
    issues = gp.get_issues()
    buf = json.dumps(issues, ensure_ascii=False, indent=2)
    print(buf)


if __name__ == '__main__':
    p = argparse.ArgumentParser(
        description='GitHub Enterprise Server Issue Exporter')
    p.add_argument('--config', required=False,
                   help='設定ファイル',
                   default=DEFAULT_CONFIG_FILE)

    args = p.parse_args()
    config = configparser.ConfigParser()
    config.read(args.config)

    main(config)
