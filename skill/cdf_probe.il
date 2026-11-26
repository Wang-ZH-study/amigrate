;; 查询 13mmrf / 18ee 库的 cell 与 CDF 参数（headless）
;; 用法：cd /home/IC && timeout 180 virtuoso -nograph < cdf_probe.il

(printf "\n=== 13mmrf cells （过滤 n12/p12/n33/p33/res/mim）\n")
(let (lib cells)
  (setq lib (ddGetObj "smic13mmrf_1233"))
  (when lib
    (foreach c lib~>cells
      (when (or (rexMatchp "n12" c~>name) (rexMatchp "p12" c~>name)
                (rexMatchp "n33" c~>name) (rexMatchp "p33" c~>name)
                (rexMatchp "res" c~>name) (rexMatchp "mim" c~>name))
        (printf "  %s\n" c~>name))))
  (unless lib (printf "  !! 无法打开 smic13mmrf_1233\n")))

(printf "\n=== 18ee cells （过滤 n18/p18/rhrpo/mime）\n")
(let (lib)
  (setq lib (ddGetObj "smic18ee"))
  (when lib
    (foreach c lib~>cells
      (when (or (rexMatchp "n18" c~>name) (rexMatchp "p18" c~>name)
                (rexMatchp "rhrpo" c~>name) (rexMatchp "mime" c~>name))
        (printf "  %s\n" c~>name))))
  (unless lib (printf "  !! 无法打开 smic18ee\n")))

;; CDF 参数
(procedure (probeCdf libName cellName)
  (let (cdf)
    (setq cdf (cdfGetBaseCellCDF (ddGetObj libName cellName)))
    (printf "\n--- CDF %s/%s ---\n" libName cellName)
    (if (null cdf)
        (printf "  (no base CDF)\n")
        (foreach p cdf~>parameters
          (printf "  %-14s type=%-8L default=%L\n" p~>name p~>type p~>defaultValue)))))

(foreach cell '("n12" "p12" "n33" "p33")
  (probeCdf "smic13mmrf_1233" cell))
(foreach cell '("n18e2r" "p18e2r" "rhrpo" "mime2r")
  (probeCdf "smic18ee" cell))

(printf "\n=== DONE\n")
(exit)