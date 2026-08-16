"""One-off generator for seed_questions.json. Not shipped; run once, then removed.

Builds a curated, de-duplicated interview-question bank from real, current sources
gathered via web search. Honesty policy: `company` is set ONLY where the SOURCE
genuinely attributes the question to that company. Here that is only the Amazon
behavioral set (datalemur's "Amazon Behavioral Interview Guide"); everything else
comes from general "top questions" lists and is stored with company="".
"""
import json

Q = []

def add(question, topic, difficulty, role="", company="", source=""):
    Q.append({
        "question": question.strip(),
        "topic": topic,
        "difficulty": difficulty,
        "role": role,
        "company": company,
        "source": source,
    })

# ---------------------------------------------------------------------------
# DSA — Blind 75 (canonical list). Source: designgurus.io/blind75 (+ LeetCode discuss)
# Phrased as self-contained prompts a tutor can pose as-is.
# ---------------------------------------------------------------------------
BLIND75_SRC = "https://www.designgurus.io/blind75 (Blind 75)"
blind75 = [
    # (prompt, topic, difficulty)
    ("Given an array of integers, return the indices of the two numbers that add up to a specific target (Two Sum).", "arrays", "easy"),
    ("Given an integer array, determine whether any value appears at least twice (Contains Duplicate).", "arrays", "easy"),
    ("Given an array where the i-th element is the price of a stock on day i, find the maximum profit from a single buy-then-sell (Best Time to Buy and Sell Stock).", "arrays", "easy"),
    ("Given two strings, determine whether one is an anagram of the other (Valid Anagram).", "strings", "easy"),
    ("Given a string of brackets, determine whether the parentheses are validly balanced (Valid Parentheses).", "stack", "easy"),
    ("Find the contiguous subarray with the largest sum in an integer array (Maximum Subarray).", "dynamic-programming", "medium"),
    ("Given an integer array, return an array where each element is the product of all others without using division (Product of Array Except Self).", "arrays", "medium"),
    ("Given an integer array, find all unique triplets that sum to zero (3Sum).", "arrays", "medium"),
    ("Given a collection of intervals, merge all overlapping intervals (Merge Intervals).", "intervals", "medium"),
    ("Given an array of strings, group the anagrams together (Group Anagrams).", "strings", "medium"),
    ("Find the contiguous subarray with the largest product within an integer array (Maximum Product Subarray).", "dynamic-programming", "medium"),
    ("Search for a target value in a rotated sorted array in O(log n) time (Search in Rotated Sorted Array).", "binary-search", "medium"),
    ("Reverse a singly linked list, iteratively and recursively (Reverse Linked List).", "linked-list", "easy"),
    ("Determine whether a linked list contains a cycle (Linked List Cycle).", "linked-list", "easy"),
    ("Given heights of vertical lines, find two that together with the x-axis hold the most water (Container With Most Water).", "two-pointers", "medium"),
    ("Find the minimum element in a rotated sorted array in O(log n) time (Find Minimum in Rotated Sorted Array).", "binary-search", "medium"),
    ("Find the length of the longest substring you can make with the same letter after at most k character replacements (Longest Repeating Character Replacement).", "strings", "medium"),
    ("Find the length of the longest substring without repeating characters (Longest Substring Without Repeating Characters).", "strings", "medium"),
    ("Given a 2D grid of '1's (land) and '0's (water), count the number of islands (Number of Islands).", "graphs", "medium"),
    ("Remove the n-th node from the end of a singly linked list in one pass (Remove Nth Node From End of List).", "linked-list", "medium"),
    ("Count the number of palindromic substrings in a string (Palindromic Substrings).", "strings", "medium"),
    ("Given an m x n matrix of heights, find cells from which water can flow to both the Pacific and Atlantic oceans (Pacific Atlantic Water Flow).", "graphs", "medium"),
    ("Find the minimum window substring of s that contains all characters of t (Minimum Window Substring).", "strings", "hard"),
    ("Invert a binary tree (Invert Binary Tree).", "trees", "easy"),
    ("Determine whether a binary tree is a valid binary search tree (Validate Binary Search Tree).", "trees", "medium"),
    ("Given a set of intervals, find the minimum number to remove so the rest are non-overlapping (Non-overlapping Intervals).", "intervals", "medium"),
    ("Construct a binary tree from its preorder and inorder traversal arrays (Construct Binary Tree from Preorder and Inorder Traversal).", "trees", "medium"),
    ("Return the k most frequent elements in an integer array (Top K Frequent Elements).", "heap", "medium"),
    ("Given a reference to a node in a connected undirected graph, return a deep copy of the graph (Clone Graph).", "graphs", "medium"),
    ("Given tasks and a cooldown n between identical tasks, find the least time to finish them all (Task Scheduler).", "greedy", "medium"),
    ("Design an algorithm to serialize and deserialize a binary tree (Serialize and Deserialize Binary Tree).", "trees", "hard"),
    ("Find the maximum path sum in a binary tree, where a path need not pass through the root (Binary Tree Maximum Path Sum).", "trees", "hard"),
    ("Find the maximum depth of a binary tree (Maximum Depth of Binary Tree).", "trees", "easy"),
    ("Given two binary trees, determine whether they are structurally identical with the same values (Same Tree).", "trees", "easy"),
    ("Return the level-order (breadth-first) traversal of a binary tree's node values (Binary Tree Level Order Traversal).", "trees", "medium"),
    ("Design an algorithm to encode a list of strings into one string and decode it back (Encode and Decode Strings).", "strings", "medium"),
    ("Given two binary trees, determine whether one is a subtree of the other (Subtree of Another Tree).", "trees", "easy"),
    ("Find the lowest common ancestor of two nodes in a binary search tree (Lowest Common Ancestor of a BST).", "trees", "medium"),
    ("Implement a trie (prefix tree) supporting insert, search, and startsWith (Implement Trie).", "trees", "medium"),
    ("Design a data structure that supports adding words and searching with '.' wildcards (Add and Search Word).", "trees", "medium"),
    ("Find the k-th smallest element in a binary search tree (Kth Smallest Element in a BST).", "trees", "medium"),
    ("Merge k sorted linked lists into one sorted list (Merge k Sorted Lists).", "heap", "hard"),
    ("Design a data structure that supports adding numbers and finding the running median (Find Median from Data Stream).", "heap", "hard"),
    ("Insert a new interval into a sorted list of non-overlapping intervals, merging if necessary (Insert Interval).", "intervals", "medium"),
    ("Find the length of the longest consecutive elements sequence in an unsorted array in O(n) (Longest Consecutive Sequence).", "arrays", "medium"),
    ("Given a board of letters and a list of words, find all words present on the board (Word Search II).", "graphs", "hard"),
    ("Given meeting time intervals, determine whether a person could attend all meetings (Meeting Rooms).", "intervals", "easy"),
    ("Given meeting time intervals, find the minimum number of conference rooms required (Meeting Rooms II).", "intervals", "medium"),
    ("Given n nodes and a list of undirected edges, determine whether they form a valid tree (Graph Valid Tree).", "graphs", "medium"),
    ("Count the number of connected components in an undirected graph (Number of Connected Components in an Undirected Graph).", "graphs", "medium"),
    ("Given a sorted dictionary of an alien language, derive the order of its characters (Alien Dictionary).", "graphs", "hard"),
    ("Given n stairs and steps of 1 or 2, count the distinct ways to reach the top (Climbing Stairs).", "dynamic-programming", "easy"),
    ("Given coin denominations and a target amount, find the fewest coins needed to make it (Coin Change).", "dynamic-programming", "medium"),
    ("Find the length of the longest strictly increasing subsequence in an array (Longest Increasing Subsequence).", "dynamic-programming", "medium"),
    ("Given distinct candidates and a target, find all unique combinations that sum to the target (Combination Sum).", "dynamic-programming", "medium"),
    ("Given houses in a row with values, find the max you can rob without robbing two adjacent houses (House Robber).", "dynamic-programming", "medium"),
    ("Solve House Robber where the houses are arranged in a circle (House Robber II).", "dynamic-programming", "medium"),
    ("Count the ways to decode a digit string into letters where 'A'->1 ... 'Z'->26 (Decode Ways).", "dynamic-programming", "medium"),
    ("Count the unique paths a robot can take from the top-left to bottom-right of an m x n grid moving only right or down (Unique Paths).", "dynamic-programming", "medium"),
    ("Given jump lengths at each index, determine whether you can reach the last index (Jump Game).", "greedy", "medium"),
    ("Given a string and a dictionary, determine whether the string can be segmented into dictionary words (Word Break).", "dynamic-programming", "medium"),
    ("Count the number of 1 bits for every integer from 0 to n (Counting Bits).", "bit-manipulation", "easy"),
    ("Reverse the bits of a 32-bit unsigned integer (Reverse Bits).", "bit-manipulation", "easy"),
    ("Given an array where every number appears twice except one, find the single number (Number of 1 Bits / Missing Number family: Single Number).", "bit-manipulation", "easy"),
    ("Given an array containing n distinct numbers from 0..n, find the one that is missing (Missing Number).", "bit-manipulation", "easy"),
    ("Add two integers without using the + or - operators (Sum of Two Integers).", "bit-manipulation", "medium"),
    ("Rotate an n x n matrix 90 degrees clockwise in place (Rotate Image).", "matrix", "medium"),
    ("Given an m x n matrix, return all its elements in spiral order (Spiral Matrix).", "matrix", "medium"),
    ("Set entire rows and columns to zero in place wherever a matrix cell is zero (Set Matrix Zeroes).", "matrix", "medium"),
    ("Given a matrix of words, determine whether a given word exists via adjacent cells (Word Search).", "graphs", "medium"),
    ("Design and implement an LRU (Least Recently Used) cache with O(1) get and put (LRU Cache).", "design", "medium"),
    ("Find the number of 1 bits (Hamming weight) in an unsigned integer (Number of 1 Bits).", "bit-manipulation", "easy"),
    ("Reorder a linked list so nodes alternate first, last, second, second-last, ... (Reorder List).", "linked-list", "medium"),
    ("Merge two sorted linked lists into one sorted list (Merge Two Sorted Lists).", "linked-list", "easy"),
]
for prompt, topic, diff in blind75:
    add(prompt, topic, diff, role="swe", source=BLIND75_SRC)

# ---------------------------------------------------------------------------
# System design. Source: designgurus.io FAANG top-25 list.
# ---------------------------------------------------------------------------
SD_SRC = "https://www.designgurus.io/blog/system-design-interview-questions-to-crack-your-next-faang-interview"
sysdesign = [
    "Design a photo-sharing service like Instagram.",
    "Design a social media news feed like Twitter's timeline.",
    "Design a video-streaming service like YouTube or Netflix.",
    "Design a recommendation system for a large content platform.",
    "Design a link-aggregation and discussion platform like Reddit.",
    "Design a real-time chat application like WhatsApp or Slack.",
    "Design a video-conferencing system like Zoom.",
    "Design a real-time collaborative document editor like Google Docs.",
    "Design a scalable notification (push/email/SMS) service.",
    "Design a URL shortening service like TinyURL or Bitly.",
    "Design a distributed web crawler.",
    "Design an API rate limiter.",
    "Design a distributed in-memory cache like Redis.",
    "Design a large-scale search engine.",
    "Design a typeahead / autocomplete suggestion service.",
    "Design a cloud file-storage and sync service like Dropbox or Google Drive.",
    "Design a distributed key-value store like DynamoDB.",
    "Design a unique ID generator for a distributed system (like Twitter Snowflake).",
    "Design a text-sharing service like Pastebin.",
    "Design a ride-sharing service like Uber or Lyft.",
    "Design a ticketing system like Ticketmaster that handles high-contention bookings.",
    "Design an e-commerce platform's product catalog and checkout flow.",
    "Design a payment system like Stripe, including idempotency and consistency.",
    "Design a parking-lot management system (object-oriented design).",
    "Design a two-sided marketplace like Airbnb.",
]
for q in sysdesign:
    add(q, "system-design", "hard", role="senior-swe", source=SD_SRC)

# ---------------------------------------------------------------------------
# ML. Source: GeeksforGeeks ML interview questions + Analytics Vidhya bias-variance.
# ---------------------------------------------------------------------------
GFG_ML = "https://www.geeksforgeeks.org/machine-learning/machine-learning-interview-questions/"
ml = [
    ("How does machine learning differ from artificial intelligence and from data science?", "easy"),
    ("What is overfitting in machine learning, and what techniques can prevent it?", "easy"),
    ("What is regularization, and how does it reduce overfitting?", "easy"),
    ("Explain L1 (Lasso) and L2 (Ridge) regularization and how Elastic Net combines them.", "medium"),
    ("Explain the confusion matrix and the metrics you can derive from it.", "easy"),
    ("What is the difference between precision and recall, and how does the F1 score combine them?", "easy"),
    ("What are Type I and Type II errors, and how do they trade off?", "medium"),
    ("Explain the AUC-ROC curve and what it tells you about a classifier.", "medium"),
    ("Is accuracy always a good metric for classification? When does it mislead?", "easy"),
    ("What is cross-validation, and why is it used?", "easy"),
    ("Explain k-fold cross-validation, leave-one-out, and the hold-out method.", "medium"),
    ("What is the difference between regularization, standardization, and normalization?", "medium"),
    ("What is feature engineering, and why does it matter?", "easy"),
    ("What is the difference between feature engineering and feature selection?", "medium"),
    ("Describe common feature-selection techniques (filter, wrapper, embedded).", "medium"),
    ("What is dimensionality reduction, and when would you use PCA?", "medium"),
    ("How do you handle categorical data? Contrast label encoding and one-hot encoding.", "easy"),
    ("What are upsampling and downsampling, and when do you use them?", "medium"),
    ("Explain the SMOTE technique for handling class imbalance.", "medium"),
    ("How do you handle missing values and duplicate records in a dataset?", "easy"),
    ("What are outliers, and what strategies exist for detecting and handling them?", "easy"),
    ("What is data leakage, and how do you prevent it in a modeling pipeline?", "medium"),
    ("Explain the bias-variance tradeoff.", "medium"),
    ("What is hyperparameter tuning, and how does grid search differ from random search?", "medium"),
    ("State the assumptions of linear regression.", "medium"),
    ("Explain gradient descent and its variants (batch, stochastic, mini-batch).", "medium"),
    ("Why is logistic regression a classification model despite its name, and what role does the sigmoid play?", "medium"),
    ("How do you choose the optimal number of clusters in k-means?", "medium"),
    ("What is multicollinearity, why is it a problem, and how do you detect it?", "medium"),
    ("What is the Variance Inflation Factor, and how do you interpret it?", "medium"),
    ("Explain information gain and entropy in decision trees.", "medium"),
    ("How do you prevent overfitting in decision trees?", "easy"),
    ("What is pruning in decision trees, and why is it useful?", "medium"),
    ("Explain Naive Bayes and the Bayes' theorem it is built on.", "medium"),
    ("What assumption makes Naive Bayes 'naive', and when does it still work well?", "medium"),
    ("Explain the difference between generative and discriminative models.", "medium"),
    ("Explain how k-nearest neighbors works and why it is called a lazy algorithm.", "easy"),
    ("How does the choice of k affect the KNN decision boundary?", "medium"),
    ("What is the curse of dimensionality, and how does it affect distance-based models?", "medium"),
    ("What is the difference between bagging and boosting?", "medium"),
    ("How does a random forest reduce variance compared to a single decision tree?", "medium"),
    ("Explain how gradient boosting (e.g. XGBoost) builds an ensemble.", "hard"),
    ("What is the difference between supervised, unsupervised, and reinforcement learning?", "easy"),
    ("How does the support vector machine find its decision boundary, and what is the kernel trick?", "hard"),
    ("What evaluation approach would you use for a highly imbalanced fraud-detection dataset?", "medium"),
]
for prompt, diff in ml:
    add(prompt, "ml", diff, role="data-scientist", source=GFG_ML)

# High-bias / high-variance diagnosis (Analytics Vidhya bias-variance guide)
AV_BV = "https://www.analyticsvidhya.com/blog/2025/08/bias-variance-tradeoff/"
add("How do you diagnose whether a model is suffering from high bias or high variance, and what do you do in each case?", "ml", "medium", role="data-scientist", source=AV_BV)
add("Why does increasing model complexity reduce bias but increase variance?", "ml", "medium", role="data-scientist", source=AV_BV)

# ---------------------------------------------------------------------------
# Deep learning. Source: youssefHosni DS interview repo + GeeksforGeeks.
# ---------------------------------------------------------------------------
DL_SRC = "https://github.com/youssefHosni/Data-Science-Interview-Questions-Answers (Deep Learning)"
dl = [
    ("Explain backpropagation and how it computes gradients through a network.", "medium"),
    ("What are activation functions, and why are non-linear ones necessary?", "easy"),
    ("Compare sigmoid, tanh, and ReLU activation functions.", "medium"),
    ("What is the vanishing gradient problem, and how do RNNs suffer from it?", "medium"),
    ("What is the exploding gradient problem, and how do you mitigate it (e.g. gradient clipping)?", "medium"),
    ("What are the main gates in an LSTM cell, and what does each one do?", "hard"),
    ("How does a GRU differ from an LSTM?", "medium"),
    ("What is dropout, and how does it regularize a neural network?", "easy"),
    ("What is batch normalization, and why does it help training?", "medium"),
    ("How does a convolutional layer work, and what are stride, padding, and kernel size?", "medium"),
    ("Why do CNNs use pooling layers, and what do max-pooling and average-pooling do?", "easy"),
    ("What is transfer learning, and when is it appropriate?", "medium"),
    ("What is the difference between a feedforward network and a recurrent network?", "easy"),
    ("Explain how weight initialization affects deep network training.", "medium"),
    ("Compare optimizers SGD, Momentum, RMSprop, and Adam.", "medium"),
    ("What is the difference between epochs, batches, and iterations?", "easy"),
    ("How do you decide the learning rate, and what is a learning-rate schedule?", "medium"),
    ("What is data augmentation, and why is it useful for image models?", "easy"),
    ("What causes a neural network to underfit, and how do you fix it?", "easy"),
    ("Explain the difference between L2 regularization and dropout as regularizers.", "medium"),
]
for prompt, diff in dl:
    add(prompt, "deep-learning", diff, role="ml-engineer", source=DL_SRC)

# ---------------------------------------------------------------------------
# LLM / transformers. Source: amirteymoori 50 AI & LLM Engineer questions.
# ---------------------------------------------------------------------------
LLM_SRC = "https://amirteymoori.com/ai-llm-engineer-interview-questions-2025/"
llm = [
    ("Explain the Transformer architecture and how it processes a sequence.", "medium"),
    ("Explain the self-attention mechanism and the roles of query, key, and value.", "medium"),
    ("What is multi-head attention, and why is it used instead of single-head attention?", "medium"),
    ("What is tokenization, and how do subword schemes like BPE affect an LLM?", "medium"),
    ("How do positional encodings work, and why are they needed in transformers?", "medium"),
    ("Contrast encoder-only, decoder-only, and encoder-decoder transformer architectures.", "medium"),
    ("What is the difference between pre-training and fine-tuning an LLM?", "easy"),
    ("What is supervised fine-tuning (SFT), and when do you use it?", "medium"),
    ("Explain RLHF (reinforcement learning from human feedback) and its purpose.", "hard"),
    ("What is LoRA, and how does it enable parameter-efficient fine-tuning?", "medium"),
    ("When would you choose QLoRA over full fine-tuning?", "medium"),
    ("What is PEFT, and what techniques does it include?", "medium"),
    ("What is chain-of-thought prompting, and when does it help?", "easy"),
    ("Explain the difference between zero-shot and few-shot prompting.", "easy"),
    ("What are system prompts, and how do they differ from user prompts?", "easy"),
    ("What prompting strategies help reduce hallucinations?", "medium"),
    ("What are vector embeddings, and how are they used in semantic search?", "easy"),
    ("What similarity metrics are used in vector search, and how do you choose one?", "medium"),
    ("What is the difference between sparse and dense retrieval?", "medium"),
    ("What metrics do you use to evaluate free-form LLM outputs?", "hard"),
    ("How do you detect hallucinations in LLM outputs?", "hard"),
    ("How do you evaluate bias in a language model?", "medium"),
    ("Name common LLM benchmarks and what each measures.", "medium"),
    ("What is model quantization, and why would you quantize an LLM?", "medium"),
    ("What is the difference between INT8 and FP16 quantization?", "medium"),
    ("What is the KV cache, and why does it matter for inference latency?", "hard"),
    ("What techniques reduce LLM inference latency?", "medium"),
    ("What are vLLM and TensorRT-LLM, and when would you use each?", "hard"),
    ("How do you scale LLM serving for production traffic?", "hard"),
    ("What are AI guardrails, and how do you implement them?", "medium"),
    ("What is a prompt-injection attack, and how do you defend against it?", "hard"),
    ("What is LLM red-teaming, and why is it important?", "medium"),
    ("What is function calling / tool use in LLMs, and how does it work?", "medium"),
    ("How do reasoning models differ from standard LLMs?", "medium"),
    ("How do multimodal models process and align different input types?", "hard"),
    ("What is the temperature parameter, and how does it affect sampling?", "easy"),
    ("Explain top-k and top-p (nucleus) sampling.", "medium"),
    ("What is a context window, and what are the challenges of long contexts?", "medium"),
    ("What is the difference between greedy decoding and beam search?", "medium"),
    ("What is catastrophic forgetting during fine-tuning, and how do you mitigate it?", "hard"),
]
for prompt, diff in llm:
    add(prompt, "llm", diff, role="ai-engineer", source=LLM_SRC)

# ---------------------------------------------------------------------------
# RAG / agents. Source: DataCamp Top-30 RAG questions.
# ---------------------------------------------------------------------------
RAG_SRC = "https://www.datacamp.com/blog/rag-interview-questions"
rag = [
    ("Explain the main components of a RAG system and how they work together.", "easy"),
    ("What are the benefits of RAG over relying only on an LLM's internal knowledge?", "easy"),
    ("What are common applications of retrieval-augmented generation?", "easy"),
    ("What types of external knowledge sources can a RAG system use?", "easy"),
    ("How does the retriever work in a RAG system, and what are common retrieval methods?", "medium"),
    ("What is the role of a vector database in a RAG pipeline?", "easy"),
    ("What are common ways to evaluate a RAG system?", "medium"),
    ("How do you handle ambiguous or incomplete queries in a RAG system?", "medium"),
    ("How do you choose the right retriever for a RAG application?", "medium"),
    ("Describe hybrid search and when it outperforms pure dense retrieval.", "medium"),
    ("Do you strictly need a vector database to implement RAG? What are the alternatives?", "medium"),
    ("How do you ensure retrieved passages are relevant and accurate?", "medium"),
    ("What techniques handle very long documents or large knowledge bases in RAG?", "medium"),
    ("How does a RAG system maintain context across a multi-turn conversation?", "medium"),
    ("Compare different chunking strategies and their pros and cons.", "medium"),
    ("What are the trade-offs between larger and smaller chunks in RAG?", "medium"),
    ("What is late chunking, and how does it differ from traditional chunking?", "hard"),
    ("How can you address bias in retrieved information or in the LLM's generation within a RAG system?", "hard"),
    ("How do you handle a dynamic or frequently changing knowledge base in RAG?", "hard"),
    ("How can you reduce latency in a real-time RAG system without sacrificing accuracy?", "hard"),
    ("How would you evaluate and improve a RAG system in a production environment?", "hard"),
    ("How do you make a production RAG system robust to failures and unexpected inputs?", "hard"),
    ("How would you design a RAG system for a specific task such as question answering or summarization?", "hard"),
    ("How do you handle out-of-date or irrelevant information in a fast-changing domain?", "hard"),
    ("How do you balance retrieval relevance and diversity for comprehensive responses?", "hard"),
    ("How do you keep the generated output consistent with the retrieved evidence?", "medium"),
    ("How do you ensure data privacy and security in a RAG system handling sensitive data?", "hard"),
    ("What is a reranker, and how does it improve retrieval quality in RAG?", "medium"),
    ("How would you design an agentic RAG system that can decide when to retrieve?", "hard"),
]
for prompt, diff in rag:
    add(prompt, "rag", diff, role="ai-engineer", source=RAG_SRC)

# A few agent-specific (LLM engineer guide)
add("How do AI agents work, and what are their key components (planning, memory, tools)?", "agents", "medium", role="ai-engineer", source=LLM_SRC)
add("What is the ReAct pattern, and how does it combine reasoning and acting in an agent?", "agents", "medium", role="ai-engineer", source=LLM_SRC)
add("How do you evaluate a multi-step agent, and what failure modes do you watch for?", "agents", "hard", role="ai-engineer", source=LLM_SRC)
add("How would you design a multi-agent orchestration system, and when is it better than a single agent?", "agents", "hard", role="ai-engineer", source=LLM_SRC)

# ---------------------------------------------------------------------------
# Statistics / probability. Source: DataLemur top-20 stats questions.
# ---------------------------------------------------------------------------
STAT_SRC = "https://datalemur.com/blog/statistics-interview-questions-data-science"
stats = [
    ("What is the probability of rolling a 6 on a fair six-sided die, and how do you generalize to k rolls?", "easy"),
    ("Calculate the expected value of a fair coin flip and explain what expected value means.", "easy"),
    ("Explain simple random sampling and why it matters.", "easy"),
    ("State the Central Limit Theorem and explain its significance in inference.", "medium"),
    ("What is a p-value, and how is it used in hypothesis testing?", "medium"),
    ("Given two events A and B, how do you compute the conditional probability P(A|B)?", "medium"),
    ("Explain Bayesian probability and give a data-science application.", "medium"),
    ("What is a 95% confidence interval, and how do you interpret it correctly?", "medium"),
    ("Describe the sampling distribution of the sample mean.", "medium"),
    ("How do you compute a z-score, and what does it represent?", "easy"),
    ("Compare and contrast the Poisson and Binomial distributions.", "medium"),
    ("What is the difference between Type I and Type II errors?", "medium"),
    ("Explain maximum likelihood estimation with an example.", "hard"),
    ("What is covariance, and how does it differ from correlation?", "medium"),
    ("Explain stratified sampling and its advantages over simple random sampling.", "medium"),
    ("How does Monte Carlo simulation work, and where is it applied?", "medium"),
    ("Explain bootstrapping and how it estimates the variability of a statistic.", "medium"),
    ("What are AR and MA models in time-series analysis?", "hard"),
    ("What is the multiple-comparisons problem, and how do you control the family-wise error rate?", "hard"),
    ("What is the law of large numbers, and how does it differ from the Central Limit Theorem?", "medium"),
    ("A/B test: how do you determine the required sample size and decide when a result is significant?", "medium"),
    ("What is statistical power, and what factors influence it?", "medium"),
    ("Explain the difference between correlation and causation with an example.", "easy"),
]
for prompt, diff in stats:
    add(prompt, "statistics", diff, role="data-scientist", source=STAT_SRC)

# ---------------------------------------------------------------------------
# SQL / data. General "most common" SQL lists (not company-attributed).
# ---------------------------------------------------------------------------
SQL_SRC = "Common SQL interview questions (GeeksforGeeks / DataLemur SQL lists)"
sql = [
    ("Write a SQL query to find the second-highest salary from an Employees table without using LIMIT or TOP.", "medium"),
    ("Write a SQL query to find the N-th highest salary per department using a window function.", "hard"),
    ("What is the difference between INNER JOIN, LEFT JOIN, RIGHT JOIN, and FULL OUTER JOIN?", "easy"),
    ("What is the difference between WHERE and HAVING clauses?", "easy"),
    ("What is the difference between RANK(), DENSE_RANK(), and ROW_NUMBER()?", "medium"),
    ("Write a query to find duplicate rows in a table and delete all but one of each.", "medium"),
    ("What is the difference between UNION and UNION ALL?", "easy"),
    ("Explain the difference between a correlated and a non-correlated subquery.", "medium"),
    ("What is a Common Table Expression (CTE), and when is a recursive CTE useful?", "medium"),
    ("Write a query to compute a running total using a window function.", "medium"),
    ("What is the difference between DELETE, TRUNCATE, and DROP?", "easy"),
    ("Explain database normalization and the trade-offs of denormalization.", "medium"),
    ("What are database indexes, and how do they speed up (and slow down) queries?", "medium"),
    ("What is the difference between a clustered and a non-clustered index?", "medium"),
    ("How do NULL values behave in comparisons, aggregates, and joins?", "medium"),
    ("Write a query to find, for each customer, their most recent order.", "medium"),
    ("Explain ACID properties in the context of database transactions.", "medium"),
    ("What is a self-join, and give an example use case.", "medium"),
    ("How would you find the top 3 products by revenue in each category using SQL?", "hard"),
    ("What is the difference between GROUP BY and PARTITION BY?", "medium"),
]
for prompt, diff in sql:
    add(prompt, "sql", diff, role="data-scientist", source=SQL_SRC)

# ---------------------------------------------------------------------------
# Behavioral — Amazon (GENUINELY company-attributed by DataLemur's guide).
# ---------------------------------------------------------------------------
BEH_AMZ = "https://datalemur.com/blog/amazon-behavioral-interview"
amazon_beh = [
    "Describe a time when you went above and beyond to ensure a customer was satisfied.",
    "Describe a project where you took full ownership from start to finish. What were the results?",
    "Tell me about a time you came up with a creative solution to a complex problem. How did it simplify the situation?",
    "Give me an example of a difficult decision you made that turned out to be correct. How did you reach it?",
    "How do you stay up to date with industry trends and continuously learn in your field?",
    "Tell me about a time you identified and developed talent within your team.",
    "Tell me about a project where you set and maintained high standards for quality.",
    "Describe a time you set ambitious goals and achieved them. What was your thought process?",
    "Give me an example of a time you took action without waiting for direction. What was the outcome?",
    "Tell me about a time you had to disagree with your team, and how you drove alignment and commitment.",
    "Tell me about a time you dug deep into a problem to uncover the root cause. What did you find?",
    "Describe a challenging project with a tight deadline and how you ensured successful delivery.",
    "Tell me about a time you had to rebuild trust with a colleague or client.",
    "Tell me about a time you had to make short-term sacrifices for long-term gains.",
    "Tell me about a time you made a bold and difficult decision.",
    "Tell me about a time you failed. What did you learn, and what would you do differently?",
]
for q in amazon_beh:
    add(q, "behavioral", "medium", role="", company="Amazon", source=BEH_AMZ)

# General behavioral (NOT company-attributed)
BEH_GEN = "Common behavioral interview questions (STAR method guides)"
beh_gen = [
    "Tell me about yourself and walk me through your background.",
    "Tell me about a time you had a conflict with a coworker and how you resolved it.",
    "Describe a time you received difficult feedback and how you responded to it.",
    "Tell me about a project you are most proud of and your specific contribution.",
    "Describe a time you had to persuade stakeholders to adopt your technical approach.",
    "Tell me about a time you missed a deadline. What happened and what did you learn?",
    "Describe a situation where you had to learn a new technology quickly to deliver.",
    "Tell me about a time you had to prioritize among many competing tasks.",
    "Describe a time you disagreed with your manager. How did you handle it?",
    "Tell me about the most technically challenging problem you have solved.",
    "Why do you want to work here, and why this role?",
    "Where do you see yourself in five years?",
    "Tell me about a time you mentored someone or helped a teammate grow.",
    "Describe a time you made a mistake in production. How did you handle it?",
]
for q in beh_gen:
    add(q, "behavioral", "easy", role="", source=BEH_GEN)

# ---------------------------------------------------------------------------
# ML system design / applied ML-engineer scenarios (general guides).
# ---------------------------------------------------------------------------
MLSD_SRC = "Common ML system design interview questions (ML-engineer guides)"
mlsd = [
    ("Design a recommendation system for an e-commerce product feed. Discuss candidate generation, ranking, and cold start.", "hard"),
    ("Design the ML system for a news-feed ranking model. How would you define labels and features?", "hard"),
    ("Design a real-time fraud-detection system. How do you handle latency, class imbalance, and concept drift?", "hard"),
    ("Design an image-search / visual similarity system using embeddings.", "hard"),
    ("How would you design an A/B testing framework to evaluate a new ranking model?", "medium"),
    ("Design a system to detect and monitor model drift in production.", "medium"),
    ("How would you serve a large model with low latency at high QPS?", "hard"),
    ("Design a feature store, and explain why online/offline consistency matters.", "hard"),
    ("How would you build a spam / abuse classification pipeline that adapts to adversaries?", "hard"),
    ("Design an end-to-end ML pipeline from data ingestion to monitoring for a churn-prediction model.", "medium"),
]
for prompt, diff in mlsd:
    add(prompt, "ml-system-design", diff, role="ml-engineer", source=MLSD_SRC)

# ---------------------------------------------------------------------------
# Dedup + validate + write.
# ---------------------------------------------------------------------------
seen = set()
deduped = []
for item in Q:
    key = item["question"].strip().lower()
    if key in seen:
        continue
    seen.add(key)
    deduped.append(item)

KEYS = {"question", "topic", "difficulty", "role", "company", "source"}
for item in deduped:
    assert set(item.keys()) == KEYS, f"bad keys: {item}"
    assert item["question"], "empty question"
    assert item["difficulty"] in ("easy", "medium", "hard", ""), item["difficulty"]

out_path = "src/eklavya/data/seed_questions.json"
with open(out_path, "w") as f:
    json.dump(deduped, f, indent=2, ensure_ascii=False)
    f.write("\n")

# Reporting
from collections import Counter
by_topic = Counter(i["topic"] for i in deduped)
by_diff = Counter(i["difficulty"] for i in deduped)
by_role = Counter(i["role"] or "(none)" for i in deduped)
company_tagged = [i for i in deduped if i["company"]]
by_company = Counter(i["company"] for i in company_tagged)

print(f"TOTAL: {len(deduped)}")
print("\nBY TOPIC:")
for k, v in sorted(by_topic.items(), key=lambda x: -x[1]):
    print(f"  {k:20s} {v}")
print("\nBY DIFFICULTY:")
for k, v in by_diff.most_common():
    print(f"  {k or '(none)':10s} {v}")
print("\nBY ROLE:")
for k, v in by_role.most_common():
    print(f"  {k:16s} {v}")
print(f"\nCOMPANY-ATTRIBUTED: {len(company_tagged)}")
for k, v in by_company.most_common():
    print(f"  {k:12s} {v}")
print(f"NOT company-attributed: {len(deduped) - len(company_tagged)}")
with_source = sum(1 for i in deduped if i['source'])
print(f"WITH SOURCE: {with_source}/{len(deduped)}")
