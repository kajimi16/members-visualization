#!/usr/bin/env python3
"""
月份范围贡献者统计脚本
功能：统计指定月份范围内所有成员的有效贡献，并按等级分类
- 优秀贡献者：有效commit >= 10次
- 卓越贡献者：有效commit >= 50次
- 有效commit定义：至少包含一个文件新增行数 >= 10行

优化特性：
1. 本地缓存机制 - 避免重复API调用
2. 增量更新 - 只处理新的commit
3. 进度显示 - 实时显示处理进度
4. JSON输出 - 生成前端可用的数据格式
5. 机器人过滤 - 使用共享的过滤规则
6. 代码量统计 - 按贡献者聚合新增/删除/变更行数，输出代码量排行（ranking.by_code）
7. 仓库矩阵 - 输出 user×repo 的 commit/代码量矩阵（repo_matrix）
8. 组织参数化 - 通过 --org 参数或 GITHUB_ORG 环境变量适配任意组织
"""

import os
import json
import time
import sys
import re
import shutil
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
import requests

# 添加父目录到路径，以便导入共享模块
sys.path.insert(0, str(Path(__file__).parent.parent))
from bot_filter import is_bot_account

# 配置
CONFIG = {
    'GITHUB_TOKEN': os.getenv('GITHUB_TOKEN') or os.getenv('GITHUB_KEY'),
    'ORG_NAME': os.getenv('GITHUB_ORG', 'Silver-yiyangyiyang'),
    'API_BASE': 'https://api.github.com',
    # 数据根目录：缓存与输出均按组织名分目录（main() 中根据组织名解析 CACHE_DIR/OUTPUT_DIR）
    'DATA_ROOT': Path(__file__).parent.parent.parent / 'docs' / 'public' / 'data',
    # 有效commit的阈值（单文件新增行数）
    'VALID_COMMIT_THRESHOLD': 10,
    # 贡献者等级阈值
    'EXCELLENT_THRESHOLD': 10,  # 优秀贡献者
    'OUTSTANDING_THRESHOLD': 50,  # 卓越贡献者
    # API调用控制
    'MAX_RETRIES': 3,
    'RETRY_DELAY': 2,
    'REQUEST_DELAY': 0.02,  # 请求间隔（秒）
}


def get_headers():
    """获取API请求头"""
    headers = {
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'quarterly-contributors-bot'
    }
    if CONFIG['GITHUB_TOKEN']:
        headers['Authorization'] = f"Bearer {CONFIG['GITHUB_TOKEN']}"
    return headers


def extract_username_from_email(email):
    """
    尝试从邮箱中提取GitHub用户名
    支持的格式：
    - 12345678+username@users.noreply.github.com
    - username@users.noreply.github.com
    """
    if not email:
        return None

    # GitHub noreply 邮箱格式
    noreply_pattern = r'^(?:\d+\+)?([^@]+)@users\.noreply\.github\.com$'
    match = re.match(noreply_pattern, email, re.IGNORECASE)
    if match:
        return match.group(1)

    return None


def search_user_by_email(email):
    """
    通过邮箱搜索GitHub用户
    注意：这会消耗额外的API调用
    """
    if not email or '@' not in email:
        return None

    # 跳过明显无效的邮箱
    if 'noreply' in email.lower() or 'localhost' in email.lower():
        return None

    url = f"{CONFIG['API_BASE']}/search/users?q={email}+in:email"
    try:
        data = fetch_api(url)
        if data and data.get('total_count', 0) == 1:
            # 只有精确匹配一个用户时才返回
            return data['items'][0]['login']
    except Exception:
        pass

    return None


def check_rate_limit():
    """检查API速率限制"""
    url = f"{CONFIG['API_BASE']}/rate_limit"
    try:
        response = requests.get(url, headers=get_headers(), timeout=10)
        if response.status_code == 200:
            data = response.json()
            core = data['resources']['core']
            remaining = core['remaining']
            limit = core['limit']
            reset_time = datetime.fromtimestamp(core['reset'])

            print(f"📊 API速率限制: {remaining}/{limit} 剩余")
            print(f"⏰ 重置时间: {reset_time.strftime('%Y-%m-%d %H:%M:%S')}")

            if remaining < 100:
                print(f"⚠️  警告: API调用次数不足100次，建议等待重置")
                return False
            return True
    except Exception as e:
        print(f"❌ 检查速率限制失败: {e}")
        return True  # 继续执行


def fetch_api(url, retries=None):
    """发送API请求（带重试和速率限制处理）"""
    if retries is None:
        retries = CONFIG['MAX_RETRIES']

    for attempt in range(retries):
        try:
            time.sleep(CONFIG['REQUEST_DELAY'])
            response = requests.get(url, headers=get_headers(), timeout=30)

            # 检查速率限制
            remaining = response.headers.get('X-RateLimit-Remaining')
            if remaining and int(remaining) < 10:
                reset_time = int(response.headers.get('X-RateLimit-Reset', 0))
                wait_time = max(reset_time - int(time.time()), 0) + 1
                print(f"⏳ API速率限制接近，等待 {wait_time} 秒...")
                time.sleep(wait_time)
                continue

            response.raise_for_status()
            return response.json()

        except requests.exceptions.HTTPError as e:
            if response.status_code == 403:
                print(f"❌ API速率限制或权限问题")
                return None
            elif response.status_code == 404:
                return None
            print(f"⚠️  HTTP错误 {response.status_code}: {e}")

        except Exception as e:
            print(f"⚠️  请求失败 (尝试 {attempt + 1}/{retries}): {e}")

        if attempt < retries - 1:
            wait_time = CONFIG['RETRY_DELAY'] * (2 ** attempt)
            print(f"⏳ 等待 {wait_time} 秒后重试...")
            time.sleep(wait_time)

    return None


def get_month_date_range(year, start_month, end_month):
    """
    获取指定月份范围的日期范围

    Args:
        year: 年份
        start_month: 开始月份 (1-12)
        end_month: 结束月份 (1-12)

    Returns:
        (start_date, end_date) ISO格式字符串
    """
    if start_month < 1 or start_month > 12 or end_month < 1 or end_month > 12:
        raise ValueError("月份必须是 1-12 之间的数字")
    if start_month > end_month:
        raise ValueError("开始月份不能大于结束月份")

    start_date = datetime(year, start_month, 1)

    # 结束时间使用结束月份的下个月第一天，便于 GitHub API 的 until 参数覆盖整月
    if end_month == 12:
        end_date = datetime(year + 1, 1, 1)
    else:
        end_date = datetime(year, end_month + 1, 1)

    return (
        start_date.strftime('%Y-%m-%dT%H:%M:%SZ'),
        end_date.strftime('%Y-%m-%dT%H:%M:%SZ')
    )


def format_period_label(year, start_month, end_month):
    """格式化月份范围标签"""
    if start_month == end_month:
        return f"{year}年{start_month}月"
    return f"{year}年{start_month}-{end_month}月"


class CacheManager:
    """缓存管理器 - 管理commit详情的本地缓存"""

    def __init__(self, cache_dir):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / 'commit_details.json'
        self.cache = self._load_cache()

    def _load_cache(self):
        """加载缓存"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"⚠️  加载缓存失败: {e}")
                return {}
        return {}

    def get(self, repo, sha):
        """获取缓存的commit详情"""
        key = f"{repo}:{sha}"
        return self.cache.get(key)

    def set(self, repo, sha, data):
        """设置缓存"""
        key = f"{repo}:{sha}"
        self.cache[key] = data

    def save(self):
        """保存缓存到文件"""
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
            print(f"💾 缓存已保存: {len(self.cache)} 条记录")
        except Exception as e:
            print(f"❌ 保存缓存失败: {e}")

    def size(self):
        """返回缓存大小"""
        return len(self.cache)

    def clear(self):
        """清理缓存目录"""
        try:
            if self.cache_dir.exists():
                shutil.rmtree(self.cache_dir)
                print(f"🗑️  缓存目录已清理: {self.cache_dir}")
        except Exception as e:
            print(f"⚠️  清理缓存失败: {e}")


def get_org_repos(org_name):
    """获取组织的所有可见仓库（含 token 授权的私有仓库）"""
    print(f"\n📁 获取组织 {org_name} 的仓库列表（含私有仓库）...")
    all_repos = []
    page = 1

    while True:
        url = f"{CONFIG['API_BASE']}/orgs/{org_name}/repos?per_page=100&page={page}&sort=updated"
        repos = fetch_api(url)

        if not repos or len(repos) == 0:
            break

        # 过滤fork仓库
        original_repos = [repo for repo in repos if not repo.get('fork', False)]
        all_repos.extend(original_repos)

        print(f"  ✓ 第{page}页: {len(original_repos)} 个原创仓库")

        if len(repos) < 100:
            break

        page += 1

    print(f"✅ 总共找到 {len(all_repos)} 个仓库")
    return all_repos


def get_commits_in_range(org_name, repo_name, since, until):
    """获取指定时间范围内的commits"""
    url = f"{CONFIG['API_BASE']}/repos/{org_name}/{repo_name}/commits"
    params = {
        'since': since,
        'until': until,
        'per_page': 100
    }

    all_commits = []
    page = 1

    while True:
        page_url = f"{url}?since={params['since']}&until={params['until']}&per_page={params['per_page']}&page={page}"
        commits = fetch_api(page_url)

        if not commits or len(commits) == 0:
            break

        all_commits.extend(commits)

        if len(commits) < 100:
            break

        page += 1

    return all_commits


def get_commit_details(org_name, repo_name, sha, cache_manager):
    """获取commit的详细信息（带缓存）"""
    # 先检查缓存
    cached = cache_manager.get(repo_name, sha)
    if cached:
        return cached

    # 从API获取
    url = f"{CONFIG['API_BASE']}/repos/{org_name}/{repo_name}/commits/{sha}"
    data = fetch_api(url)

    if data:
        # 提取需要的信息
        details = {
            'sha': sha[:8],
            'author': data['commit']['author']['name'],
            'author_email': data['commit']['author'].get('email', ''),
            'author_login': data['author']['login'] if data.get('author') else None,
            'date': data['commit']['author']['date'],
            'message': data['commit']['message'].split('\n')[0][:100],
            'files': []
        }

        # 提取文件变更信息
        if 'files' in data:
            for file in data['files']:
                details['files'].append({
                    'filename': file['filename'],
                    'additions': file.get('additions', 0),
                    'deletions': file.get('deletions', 0),
                    'changes': file.get('changes', 0)
                })

        # 缓存结果
        cache_manager.set(repo_name, sha, details)
        return details

    return None


def is_valid_commit(commit_details):
    """
    判断是否为有效commit
    有效commit定义：至少有一个文件的新增行数 >= 阈值
    """
    if not commit_details or 'files' not in commit_details:
        return False

    threshold = CONFIG['VALID_COMMIT_THRESHOLD']
    for file in commit_details['files']:
        if file.get('additions', 0) >= threshold:
            return True

    return False


def record_commit(stats, username, repo_name, details):
    """
    将单个有效commit计入贡献者统计（纯函数，便于测试）

    仅在有效commit时调用（与现有口径一致：valid_commits/total_commits
    以及代码量均只统计有效commit，即至少一个文件新增行数 >= 阈值）。

    累计字段：
    - valid_commits / total_commits: 有效commit数
    - additions / deletions / changes: 新增/删除/变更行数
    - repo_stats: 该贡献者在每个仓库的 commit/代码量明细
    """
    data = stats.setdefault(username, {
        'username': username,
        'verified': True,
        'valid_commits': 0,
        'total_commits': 0,
        'additions': 0,
        'deletions': 0,
        'changes': 0,
        'repos': set(),
        'repo_stats': {},
        'commits_detail': []
    })

    data['valid_commits'] += 1
    data['total_commits'] += 1
    data['repos'].add(repo_name)

    additions = sum(f['additions'] for f in details['files'])
    deletions = sum(f['deletions'] for f in details['files'])
    changes = additions + deletions

    data['additions'] += additions
    data['deletions'] += deletions
    data['changes'] += changes

    repo_key = data['repo_stats'].setdefault(
        repo_name, {'commits': 0, 'additions': 0, 'deletions': 0}
    )
    repo_key['commits'] += 1
    repo_key['additions'] += additions
    repo_key['deletions'] += deletions

    data['commits_detail'].append({
        'repo': repo_name,
        'sha': details['sha'],
        'message': details['message'],
        'date': details['date'],
        'files_count': len(details['files']),
        'total_additions': additions,
        'total_deletions': deletions,
        'total_changes': changes
    })


def process_repository(org_name, repo_name, since, until, cache_manager, stats):
    """
    处理单个仓库的统计

    Args:
        org_name: 组织名称
        repo_name: 仓库名称
        since: 开始时间
        until: 结束时间
        cache_manager: 缓存管理器
        stats: 统计数据字典（会被修改）

    Returns:
        处理的commit数量
    """
    print(f"\n  📦 处理仓库: {repo_name}")

    # 获取时间范围内的commits
    commits = get_commits_in_range(org_name, repo_name, since, until)
    if not commits:
        print(f"    ℹ️  无commit")
        return 0

    print(f"    ✓ 找到 {len(commits)} 个commit")

    valid_count = 0
    processed_count = 0

    for i, commit in enumerate(commits):
        sha = commit['sha']
        # 从列表API中提取author login（列表API有时能关联到用户，详情API却不行）
        list_author_login = commit.get('author', {}).get('login') if commit.get('author') else None

        # 提前过滤机器人账户（避免不必要的详情API调用）
        if list_author_login and is_bot_account(list_author_login):
            continue

        # 获取commit详情
        details = get_commit_details(org_name, repo_name, sha, cache_manager)
        if not details:
            continue

        processed_count += 1

        # 判断是否为有效commit
        if is_valid_commit(details):
            valid_count += 1

            # 获取作者信息 - 多种方式尝试解析GitHub用户名
            author_login = details.get('author_login')
            is_verified = True

            # 方式1: 使用列表API中的author login
            if not author_login and list_author_login:
                author_login = list_author_login

            # 方式2: 从邮箱中提取用户名（GitHub noreply格式）
            if not author_login:
                author_email = details.get('author_email', '')
                author_login = extract_username_from_email(author_email)
                if author_login:
                    print(f"    📧 从邮箱解析用户名: {author_login}")

            # 方式3: 通过邮箱搜索GitHub用户（消耗额外API）
            if not author_login:
                author_email = details.get('author_email', '')
                if author_email and '@' in author_email:
                    author_login = search_user_by_email(author_email)
                    if author_login:
                        print(f"    🔍 通过邮箱搜索到用户: {author_login}")

            # 方式4: 无法解析，使用commit作者名，标记为未验证
            if not author_login:
                author_login = details.get('author', 'Unknown')
                is_verified = False
                print(f"    ⚠️  未能解析GitHub用户名，使用作者名: {author_login}")

            # 检查是否为机器人账户（使用共享的过滤规则）
            if is_bot_account(author_login):
                print(f"    🤖 跳过机器人账户: {author_login}")
                continue

            # 记录到统计数据
            if author_login not in stats:
                stats[author_login] = {
                    'username': author_login,
                    'verified': is_verified,
                    'valid_commits': 0,
                    'total_commits': 0,
                    'additions': 0,
                    'deletions': 0,
                    'changes': 0,
                    'repos': set(),
                    'repo_stats': {},
                    'commits_detail': []
                }
            # 如果之前是未验证的，现在有验证的commit，更新为已验证
            elif is_verified and not stats[author_login].get('verified'):
                stats[author_login]['verified'] = True

            record_commit(stats, author_login, repo_name, details)

        # 显示进度
        if (i + 1) % 50 == 0:
            print(f"    📊 进度: {i + 1}/{len(commits)} commits")

    print(f"    ✅ 有效commit: {valid_count}/{processed_count}")
    return processed_count


def classify_contributors(stats):
    """
    对贡献者进行分级

    Returns:
        {
            'outstanding': [...],  # 卓越贡献者 (>=50)
            'excellent': [...],    # 优秀贡献者 (>=10)
            'active': [...]        # 活跃贡献者 (<10)
        }
    """
    outstanding = []
    excellent = []
    active = []

    for username, data in stats.items():
        valid_commits = data['valid_commits']

        contributor = {
            'username': username,
            'verified': data.get('verified', True),
            'valid_commits': valid_commits,
            'total_commits': data['total_commits'],
            'additions': data['additions'],
            'deletions': data['deletions'],
            'changes': data['changes'],
            'repos_count': len(data['repos']),
            'repos': sorted(list(data['repos'])),
            'recent_commits': sorted(
                data['commits_detail'],
                key=lambda x: x['date'],
                reverse=True
            )[:10]  # 只保留最近10个commit
        }

        if valid_commits >= CONFIG['OUTSTANDING_THRESHOLD']:
            outstanding.append(contributor)
        elif valid_commits >= CONFIG['EXCELLENT_THRESHOLD']:
            excellent.append(contributor)
        else:
            active.append(contributor)

    # 按有效commit数量降序排序
    outstanding.sort(key=lambda x: x['valid_commits'], reverse=True)
    excellent.sort(key=lambda x: x['valid_commits'], reverse=True)
    active.sort(key=lambda x: x['valid_commits'], reverse=True)

    return {
        'outstanding': outstanding,
        'excellent': excellent,
        'active': active
    }


def build_ranking(stats):
    """
    构建贡献者排行（纯函数，便于测试）

    Returns:
        {
            'by_commits': [...],  # 按有效commit数降序（并列时按新增行数）
            'by_code': [...]      # 按新增行数降序（并列时按有效commit数）
        }
        每个条目含 rank 字段（1 起始）
    """
    contributors = []
    for username, data in stats.items():
        contributors.append({
            'username': username,
            'verified': data.get('verified', True),
            'valid_commits': data['valid_commits'],
            'total_commits': data['total_commits'],
            'additions': data['additions'],
            'deletions': data['deletions'],
            'changes': data['changes'],
            'repos_count': len(data['repos']),
        })

    by_commits = sorted(
        contributors,
        key=lambda x: (x['valid_commits'], x['additions']),
        reverse=True
    )
    by_code = sorted(
        contributors,
        key=lambda x: (x['additions'], x['valid_commits']),
        reverse=True
    )

    for i, entry in enumerate(by_commits):
        entry['commit_rank'] = i + 1
    for i, entry in enumerate(by_code):
        entry['code_rank'] = i + 1

    return {
        'by_commits': by_commits,
        'by_code': by_code,
    }


def build_repo_matrix(stats):
    """
    构建 user×repo 代码量矩阵（纯函数，便于测试）

    Returns:
        {
            'repo_name': {
                'username': {'commits': n, 'additions': n, 'deletions': n}
            }
        }
    """
    matrix = {}
    for username, data in stats.items():
        for repo_name, rs in data.get('repo_stats', {}).items():
            matrix.setdefault(repo_name, {})[username] = {
                'commits': rs['commits'],
                'additions': rs['additions'],
                'deletions': rs['deletions'],
            }
    return matrix


def update_monthly_index(output_dir):
    """重建前端可用的月份范围索引"""
    output_dir = Path(output_dir)
    index_items = []

    for file_path in output_dir.glob('monthly_contributors_*.json'):
        if file_path.name == 'monthly_contributors_index.json':
            continue

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"⚠️  跳过无法读取的数据文件 {file_path.name}: {e}")
            continue

        meta = data.get('meta', {})
        year = meta.get('year')
        start_month = meta.get('start_month')
        end_month = meta.get('end_month')
        if not year or not start_month or not end_month:
            print(f"⚠️  跳过缺少月份范围元数据的文件: {file_path.name}")
            continue

        index_items.append({
            'year': year,
            'start_month': start_month,
            'end_month': end_month,
            'period_label': meta.get('period_label') or format_period_label(year, start_month, end_month),
            'filename': file_path.name,
            'generated_at': meta.get('generated_at'),
            'total_contributors': meta.get('total_contributors', 0),
            'outstanding_count': meta.get('outstanding_count', 0),
            'excellent_count': meta.get('excellent_count', 0),
            'active_count': meta.get('active_count', 0),
        })

    index_items.sort(
        key=lambda item: (item['year'], item['end_month'], item['start_month']),
        reverse=True
    )

    index_file = output_dir / 'monthly_contributors_index.json'
    with open(index_file, 'w', encoding='utf-8') as f:
        json.dump(index_items, f, ensure_ascii=False, indent=2)

    print(f"🧭 月份范围索引已更新: {index_file}")
    return index_file


def save_results(year, start_month, end_month, classified, stats, output_dir):
    """保存统计结果到JSON文件（含代码量排行与user×repo矩阵）"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 生成文件名
    filename = f"monthly_contributors_{year}_{start_month:02d}_{end_month:02d}.json"
    output_file = output_dir / filename

    # 准备输出数据
    ranking = build_ranking(stats)
    repo_matrix = build_repo_matrix(stats)

    result = {
        'meta': {
            'year': year,
            'start_month': start_month,
            'end_month': end_month,
            'org_name': CONFIG['ORG_NAME'],
            'period_label': format_period_label(year, start_month, end_month),
            'period_type': 'monthly_range',
            'generated_at': datetime.now().isoformat(),
            'total_contributors': len(stats),
            'outstanding_count': len(classified['outstanding']),
            'excellent_count': len(classified['excellent']),
            'active_count': len(classified['active']),
            'total_additions': sum(d['additions'] for d in stats.values()),
            'total_deletions': sum(d['deletions'] for d in stats.values()),
            'total_changes': sum(d['changes'] for d in stats.values()),
            'thresholds': {
                'outstanding': CONFIG['OUTSTANDING_THRESHOLD'],
                'excellent': CONFIG['EXCELLENT_THRESHOLD'],
                'valid_commit_threshold': CONFIG['VALID_COMMIT_THRESHOLD']
            }
        },
        'contributors': classified,
        'ranking': ranking,
        'repo_matrix': repo_matrix
    }
    # 保存到文件
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    update_monthly_index(output_dir)

    print(f"\n💾 结果已保存到: {output_file}")
    return output_file


def print_summary(classified, stats):
    """打印统计摘要"""
    print("\n" + "="*60)
    print("📊 统计摘要")
    print("="*60)

    print(f"\n🏆 卓越贡献者 (>={CONFIG['OUTSTANDING_THRESHOLD']}次有效commit): {len(classified['outstanding'])}人")
    for contributor in classified['outstanding'][:5]:
        print(f"  - {contributor['username']}: {contributor['valid_commits']}次 ({contributor['repos_count']}个仓库)")

    print(f"\n⭐ 优秀贡献者 (>={CONFIG['EXCELLENT_THRESHOLD']}次有效commit): {len(classified['excellent'])}人")
    for contributor in classified['excellent'][:5]:
        print(f"  - {contributor['username']}: {contributor['valid_commits']}次 ({contributor['repos_count']}个仓库)")

    print(f"\n👥 活跃贡献者 (<{CONFIG['EXCELLENT_THRESHOLD']}次有效commit): {len(classified['active'])}人")
    print(f"\n📝 代码量排行 TOP5（按新增行数）:")
    by_code = sorted(
        stats.items(),
        key=lambda kv: kv[1]['additions'],
        reverse=True
    )[:5]
    for contributor, data in by_code:
        print(f"  - {contributor}: +{data['additions']} / -{data['deletions']} 行 ({data['valid_commits']}次有效commit)")

    print("\n" + "="*60)



def main(year, start_month, end_month, org_name=None):
    """
    主函数：统计指定月份范围的贡献者

    Args:
        year: 年份
        start_month: 开始月份 (1-12)
        end_month: 结束月份 (1-12)
        org_name: GitHub 组织名（None 时使用 CONFIG['ORG_NAME']）
    """
    if org_name:
        CONFIG['ORG_NAME'] = org_name

    # 缓存与输出目录按组织名隔离
    CONFIG['CACHE_DIR'] = CONFIG['DATA_ROOT'] / 'cache' / CONFIG['ORG_NAME']
    CONFIG['OUTPUT_DIR'] = CONFIG['DATA_ROOT'] / CONFIG['ORG_NAME']

    print("="*60)
    print(f"🚀 开始统计 {CONFIG['ORG_NAME']} 组织 {format_period_label(year, start_month, end_month)} 贡献者")
    print("="*60)

    # 检查API速率限制
    if not check_rate_limit():
        print("⚠️  API调用次数不足，建议稍后再试")
        return

    # 初始化缓存管理器
    cache_manager = CacheManager(CONFIG['CACHE_DIR'])
    print(f"📦 缓存已加载: {cache_manager.size()} 条记录")

    # 获取月份范围
    since, until = get_month_date_range(year, start_month, end_month)
    print(f"📅 统计时间范围: {since} 至 {until}")

    # 获取组织仓库
    repos = get_org_repos(CONFIG['ORG_NAME'])
    if not repos:
        print("❌ 未找到任何仓库")
        return

    # 统计数据
    stats = {}
    total_commits = 0
    start_time = time.time()

    # 处理每个仓库
    for i, repo in enumerate(repos):
        repo_name = repo['name']
        print(f"\n[{i+1}/{len(repos)}] 处理仓库: {repo_name}")

        try:
            commit_count = process_repository(
                CONFIG['ORG_NAME'],
                repo_name,
                since,
                until,
                cache_manager,
                stats
            )
            total_commits += commit_count

            # 每处理10个仓库保存一次缓存
            if (i + 1) % 10 == 0:
                cache_manager.save()

        except Exception as e:
            print(f"  ❌ 处理失败: {e}")
            continue

    # 保存最终缓存
    cache_manager.save()

    # 对贡献者进行分级
    print("\n📊 正在分级贡献者...")
    classified = classify_contributors(stats)

    # 打印摘要
    print_summary(classified, stats)

    # 保存结果
    output_file = save_results(
        year,
        start_month,
        end_month,
        classified,
        stats,
        CONFIG['OUTPUT_DIR']
    )

    # 显示执行统计
    elapsed_time = time.time() - start_time
    print(f"\n⏱️  总耗时: {elapsed_time:.1f} 秒")
    print(f"📊 处理仓库: {len(repos)} 个")
    print(f"📊 总commit数: {total_commits}")
    print(f"📊 总贡献者: {len(stats)} 人")

    print("\n✅ 统计完成！")
    return output_file


def get_previous_month():
    """
    获取上一个月份的年份和月份
    例如：当前是2026年1月，返回 (2025, 12)
    """
    now = datetime.now()
    if now.month == 1:
        return now.year - 1, 12
    return now.year, now.month - 1


def get_current_month():
    """获取当前月份的年份和月份"""
    now = datetime.now()
    return now.year, now.month


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='月份范围贡献者统计：按成员聚合 commit 数与代码量并输出排行'
    )
    parser.add_argument(
        '--org', default=None,
        help='GitHub 组织名（默认取环境变量 GITHUB_ORG，其次 Silver-yiyangyiyang）'
    )
    parser.add_argument('--last', action='store_true', help='统计上个月')
    parser.add_argument('--current', action='store_true', help='统计当前月')
    parser.add_argument('year', nargs='?', type=int, help='年份（与开始/结束月份一起使用）')
    parser.add_argument('start_month', nargs='?', type=int, help='开始月份 1-12')
    parser.add_argument('end_month', nargs='?', type=int, help='结束月份 1-12')
    args = parser.parse_args()

    try:
        if args.last and args.current:
            print("❌ --last 与 --current 不能同时使用")
            sys.exit(1)

        if args.last:
            year, month = get_previous_month()
            print(f"📅 自动选择上个月: {year}年{month}月")
            main(year, month, month, args.org)
        elif args.current:
            year, month = get_current_month()
            print(f"📅 自动选择当前月: {year}年{month}月")
            main(year, month, month, args.org)
        elif args.year is not None:
            if args.start_month is None or args.end_month is None:
                print("❌ 缺少参数，用法: python quarterly_contributors.py [--org 组织名] <年份> <开始月份> <结束月份>")
                sys.exit(1)
            if args.start_month < 1 or args.start_month > 12 or args.end_month < 1 or args.end_month > 12:
                print("❌ 月份必须是 1-12 之间的数字")
                sys.exit(1)
            if args.start_month > args.end_month:
                print("❌ 开始月份不能大于结束月份")
                sys.exit(1)
            main(args.year, args.start_month, args.end_month, args.org)
        else:
            parser.print_help()
            sys.exit(0)
    except ValueError:
        print("❌ 参数格式错误，年份和月份必须是数字")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断执行")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ 执行失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
