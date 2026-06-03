import React from 'react';

/**
 * Simple markdown renderer for chat messages
 * Handles: bold, italic, code, lists (with nesting), headers, line breaks
 */
const MarkdownRenderer = ({ content }) => {
  if (!content) return null;

  const processInlineMarkdown = (text) => {
    if (!text) return null;
    
    const parts = [];
    let currentIndex = 0;

    // Pattern to match: **bold**, *italic*, `code`, or regular text
    const patterns = [
      { regex: /\*\*([^*]+)\*\*/g, type: 'bold' },
      { regex: /\*([^*]+)\*/g, type: 'italic' },
      { regex: /`([^`]+)`/g, type: 'code' },
    ];

    while (currentIndex < text.length) {
      let earliestMatch = null;
      let earliestIndex = text.length;

      // Find the earliest match
      for (const pattern of patterns) {
        pattern.regex.lastIndex = currentIndex;
        const match = pattern.regex.exec(text);
        if (match && match.index < earliestIndex) {
          earliestMatch = { ...match, type: pattern.type };
          earliestIndex = match.index;
        }
      }

      if (earliestMatch) {
        // Add text before match
        if (earliestIndex > currentIndex) {
          parts.push({ type: 'text', content: text.substring(currentIndex, earliestIndex) });
        }

        // Add formatted text
        const formattedContent = earliestMatch[1];
        if (earliestMatch.type === 'bold') {
          parts.push({ type: 'bold', content: formattedContent });
        } else if (earliestMatch.type === 'italic') {
          parts.push({ type: 'italic', content: formattedContent });
        } else if (earliestMatch.type === 'code') {
          parts.push({ type: 'code', content: formattedContent });
        }

        currentIndex = earliestIndex + earliestMatch[0].length;
      } else {
        // No more matches, add remaining text
        if (currentIndex < text.length) {
          parts.push({ type: 'text', content: text.substring(currentIndex) });
        }
        break;
      }
    }

    return parts.map((part, idx) => {
      if (part.type === 'text') {
        return <span key={`text-${idx}`}>{part.content}</span>;
      } else if (part.type === 'bold') {
        return <strong key={`bold-${idx}`}>{part.content}</strong>;
      } else if (part.type === 'italic') {
        return <em key={`italic-${idx}`}>{part.content}</em>;
      } else if (part.type === 'code') {
        return (
          <code
            key={`code-${idx}`}
            style={{
              backgroundColor: '#f4f4f4',
              padding: '2px 6px',
              borderRadius: '3px',
              fontFamily: 'monospace',
              fontSize: '0.9em'
            }}
          >
            {part.content}
          </code>
        );
      }
      return null;
    });
  };

  // Helper to calculate indentation level (count leading spaces, 2 spaces = 1 level)
  const getIndentLevel = (line) => {
    const match = line.match(/^(\s*)/);
    if (!match) return 0;
    const spaces = match[1].length;
    return Math.floor(spaces / 2); // 2 spaces = 1 indent level
  };

  // Helper to check if line is a list item
  const isListItem = (line) => {
    const trimmed = line.trim();
    return /^[-*]\s+/.test(trimmed) || /^\d+\.\s+/.test(trimmed);
  };

  // Build nested list tree structure
  const buildListTree = (items) => {
    if (items.length === 0) return null;

    const root = { level: -1, children: [] };
    const stack = [{ node: root, level: -1 }];

    items.forEach((item) => {
      // Pop stack until we find the parent for this item's level
      while (stack.length > 1 && stack[stack.length - 1].level >= item.level) {
        stack.pop();
      }

      const parent = stack[stack.length - 1].node;
      const listItem = {
        level: item.level,
        content: item.content,
        children: []
      };

      parent.children.push(listItem);

      // Push this item as potential parent for next items
      stack.push({ node: listItem, level: item.level });
    });

    return root.children;
  };

  // Render list tree recursively
  const renderListTree = (items, keyPrefix = '') => {
    if (!items || items.length === 0) return null;

    return (
      <ul key={keyPrefix} style={{ margin: '4px 0', paddingLeft: '20px', listStyleType: 'disc' }}>
        {items.map((item, idx) => (
          <li key={`${keyPrefix}-${idx}`} style={{ marginBottom: '4px' }}>
            {item.content}
            {item.children && item.children.length > 0 && renderListTree(item.children, `${keyPrefix}-${idx}`)}
          </li>
        ))}
      </ul>
    );
  };

  // Process content line by line
  const lines = content.split('\n');
  const elements = [];
  let codeBlockContent = [];
  let listItems = [];
  let inCodeBlock = false;
  let inList = false;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmedLine = line.trim();

    // Code blocks
    if (trimmedLine.startsWith('```')) {
      if (inCodeBlock) {
        // End code block
        inCodeBlock = false;
        const codeContent = codeBlockContent.join('\n');
        codeBlockContent = [];
        elements.push(
          <pre
            key={`codeblock-${i}`}
            style={{
              backgroundColor: '#f4f4f4',
              padding: '12px',
              borderRadius: '4px',
              overflowX: 'auto',
              fontFamily: 'monospace',
              fontSize: '0.9em',
              margin: '10px 0',
              border: '1px solid #ddd'
            }}
          >
            <code>{codeContent}</code>
          </pre>
        );
      } else {
        // Start code block
        inCodeBlock = true;
      }
      continue;
    }

    if (inCodeBlock) {
      codeBlockContent.push(line);
      continue;
    }

    // Flush list if we encounter a non-list item (and not empty line)
    if (inList && trimmedLine !== '' && !isListItem(line)) {
      inList = false;
      const listTree = buildListTree(listItems);
      if (listTree) {
        elements.push(renderListTree(listTree, `list-${i}`));
      }
      listItems = [];
    }

    // Headers
    if (trimmedLine.startsWith('### ')) {
      if (inList) {
        const listTree = buildListTree(listItems);
        if (listTree) {
          elements.push(renderListTree(listTree, `list-${i}-pre`));
        }
        listItems = [];
        inList = false;
      }
      elements.push(
        <h3 key={`h3-${i}`} style={{ margin: '12px 0 8px 0', fontSize: '1.1em', fontWeight: '600' }}>
          {processInlineMarkdown(trimmedLine.substring(4))}
        </h3>
      );
      continue;
    }
    if (trimmedLine.startsWith('## ')) {
      if (inList) {
        const listTree = buildListTree(listItems);
        if (listTree) {
          elements.push(renderListTree(listTree, `list-${i}-pre`));
        }
        listItems = [];
        inList = false;
      }
      elements.push(
        <h2 key={`h2-${i}`} style={{ margin: '14px 0 10px 0', fontSize: '1.2em', fontWeight: '600' }}>
          {processInlineMarkdown(trimmedLine.substring(3))}
        </h2>
      );
      continue;
    }
    if (trimmedLine.startsWith('# ')) {
      if (inList) {
        const listTree = buildListTree(listItems);
        if (listTree) {
          elements.push(renderListTree(listTree, `list-${i}-pre`));
        }
        listItems = [];
        inList = false;
      }
      elements.push(
        <h1 key={`h1-${i}`} style={{ margin: '16px 0 12px 0', fontSize: '1.3em', fontWeight: '600' }}>
          {processInlineMarkdown(trimmedLine.substring(2))}
        </h1>
      );
      continue;
    }

    // Lists - handle indentation
    if (isListItem(line)) {
      const indentLevel = getIndentLevel(line);
      const listContent = trimmedLine.replace(/^[-*]\s+/, '').replace(/^\d+\.\s+/, '');
      
      if (!inList) {
        inList = true;
      }
      
      listItems.push({
        level: indentLevel,
        content: processInlineMarkdown(listContent)
      });
      continue;
    }

    // Regular line
    if (trimmedLine === '') {
      // Empty line - might be list continuation or paragraph break
      if (!inList) {
        elements.push(<br key={`br-${i}`} />);
      }
    } else {
      if (inList) {
        // Flush list before regular text
        const listTree = buildListTree(listItems);
        if (listTree) {
          elements.push(renderListTree(listTree, `list-${i}-pre`));
        }
        listItems = [];
        inList = false;
      }
      elements.push(
        <div key={`line-${i}`} style={{ marginBottom: '8px' }}>
          {processInlineMarkdown(trimmedLine)}
        </div>
      );
    }
  }

  // Flush any remaining list
  if (inList && listItems.length > 0) {
    const listTree = buildListTree(listItems);
    if (listTree) {
      elements.push(renderListTree(listTree, 'list-final'));
    }
  }

  // Flush any remaining code block
  if (inCodeBlock && codeBlockContent.length > 0) {
    elements.push(
      <pre
        key="codeblock-final"
        style={{
          backgroundColor: '#f4f4f4',
          padding: '12px',
          borderRadius: '4px',
          overflowX: 'auto',
          fontFamily: 'monospace',
          fontSize: '0.9em',
          margin: '10px 0',
          border: '1px solid #ddd'
        }}
      >
        <code>{codeBlockContent.join('\n')}</code>
      </pre>
    );
  }

  return <div>{elements}</div>;
};

export default MarkdownRenderer;
