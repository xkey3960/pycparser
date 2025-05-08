DOT_FILE_BEGIN = '''
digraph G {
    rankdir=LR;
    node [shape=box];
'''

DOT_FILE_END = '''
}
'''

def transform_rules(input_file, output_file):
    edges = set()

    with open(input_file, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or '->' not in line:
                continue
            
            # 分割左右部分
            left_part, right_part = line.split('->', 1)
            
            # 提取左边符号（取最后一个单词）
            left_side = left_part.split()[-1].strip()
            
            # 处理右边符号
            right_symbols = right_part.strip().split()
            if not right_symbols:
                continue
            
            # 根据右边符号数量处理
            if len(right_symbols) == 1:
                edges.add((left_side, right_symbols[0]))
            else:
                combined = '_'.join(right_symbols)
                edges.add((left_side, combined))
                for symbol in right_symbols:
                    edges.add((combined, symbol))

    # 写入输出文件
    with open(output_file, 'w') as f:
        f.write(DOT_FILE_BEGIN)
        for src, dest in edges:
            f.write(f"{src} -> {dest}\n")
        f.write(DOT_FILE_END)

# 使用示例
transform_rules('rules.txt', 'graph.dot')

''' 
生成png文件:
dot -Tpng graph.dot -o grammar.png 
'''